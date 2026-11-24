#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le test long des bureaux, sans VM : ses parties pures.

long_test/qemu_desktops.py crée soixante-dix VM et dure des heures ; ceux-ci
tiennent en quelques secondes ce qui le rend juste :

- la matrice est la table du menu entière, et un filtre inconnu est refusé
  avant toute création ;
- la commande de déploiement et la commande distante sont celles du menu ;
- les sorties de l'invité se lisent sans se tromper de processus (un shell
  qui porte le nom cherché n'est pas la session), de port ou d'unité ;
- le verdict échoue sur chaque défaut connu, et n'excuse que ce qui est
  nommé : mcelog, le rc 4 de nixos-rebuild, l'écran sans barre d'i3 sur
  Leap 16 ;
- l'image se juge à ses teintes, et le client RFB lit un vrai serveur.
"""

import contextlib
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "long_test"))

import qemu_desktops as q  # noqa: E402
import qemu_desktops_image as img  # noqa: E402

CLIENT = RACINE / "long_test" / "qemu_desktops_client"


def todo():
    return q.charger_todo()


def vert_krdp(**changes):
    """Un résultat de VM KRdp Fedora complet et vert."""
    r = {
        "vm": "ldesk-fedora-44-plasma",
        "distro": "fedora",
        "version": "44",
        "flavour": "plasma",
        "kind": "krdp",
        "access": "krdp",
        "port": "3389",
        "mgr": "dnf",
        "deploy": "0 25s",
        "ip": "192.0.2.10",
        "cloud_final": "active",
        "install": "0 700s",
        "install_warn": "0",
        "reboot_ssh": "ok",
        "ip_after": "192.0.2.10",
        "dm": "plasmalogin.service active",
        "failed_units": "",
        "autologin": "yes",
        "locked": "yes",
        "hyprlock": "ABSENT",
        "port_listen": "ok",
        "motd_port": "ok",
        "console_shot": "saved 1280 800",
        "rdp_bad": "alive=0 rc=1",
        "rdp_bad_pam": "2",
        "rdp_good": "alive=1",
        "rdp_good_pam": "0",
        "rdp_good_img": "colours=5000 nonblack=99.80",
        "faillock_good_after": "alive=1",
        "done": "1",
    }
    r.update(changes)
    return r


class LaPlace(unittest.TestCase):
    def test_it_lives_out_of_the_unit_runner(self):
        self.assertTrue((RACINE / "long_test" / "qemu_desktops.py").is_file())
        self.assertFalse((RACINE / "test" / "qemu_desktops.py").exists())

    def test_scripts_are_executable(self):
        for nom in ("qemu_desktops.py", "qemu_desktops_image.py"):
            self.assertTrue(os.access(RACINE / "long_test" / nom, os.X_OK))

    def test_guest_probe_never_uses_pgrep(self):
        # « pgrep -f » lancé par ssh se trouve dans la ligne de commande du
        # shell qui le porte : la session paraissait vivante sans l'être.
        self.assertNotIn("pgrep", q.SONDE_INVITE)

    def test_client_files_ship_with_the_test(self):
        self.assertIn("freerdp", (CLIENT / "Containerfile").read_text())
        rdp = (CLIENT / "rdp.sh").read_text()
        # Deux conteneurs en réseau hôte tirant le même écran : sans
        # « -nolisten local », le second Xvfb meurt et son client rejoint
        # l'écran de l'autre.
        self.assertIn("-nolisten local", rdp)
        self.assertIn("/pw/good", rdp)
        self.assertNotIn("$PASSWORD", rdp)


class Matrice(unittest.TestCase):
    def setUp(self):
        self.table = todo()._QEMU_DESKTOP_RELEASES

    def test_default_is_the_whole_table(self):
        attendu = sum(
            len(vs) for t in self.table.values() for vs in t.values()
        )
        self.assertEqual(len(q.matrice(self.table)), attendu)
        self.assertGreater(attendu, 60)

    def test_filters_combine(self):
        combos = q.matrice(self.table, ["plasma"], ["fedora", "rocky"])
        self.assertEqual(
            combos,
            [
                ("fedora", "44", "plasma"),
                ("fedora", "45", "plasma"),
                ("rocky", "10", "plasma"),
            ],
        )
        self.assertEqual(
            q.matrice(self.table, ["i3"], ["opensuse"], ["16.0"]),
            [("opensuse", "16.0", "i3")],
        )

    def test_unknown_names_refused_before_anything(self):
        for args in (
            (["kde"], [], []),
            ([], ["gentoo"], []),
            ([], [], ["99"]),
        ):
            with self.assertRaises(ValueError):
                q.matrice(self.table, *args)

    def test_names_unique_and_valid_hostnames(self):
        noms = [q.nom_vm("ldesk", *c) for c in q.matrice(self.table)]
        self.assertEqual(len(noms), len(set(noms)))
        for nom in noms:
            self.assertRegex(nom, r"^ldesk-[a-z0-9-]+$")
            self.assertLessEqual(len(nom), 63)
        self.assertEqual(
            q.nom_vm("ldesk", "opensuse", "16.0", "xfce"),
            "ldesk-opensuse-160-xfce",
        )

    def test_parallel_advice_follows_ram(self):
        # 24 Go disponibles : six VM de 4 Go ne laisseraient rien à l'hôte.
        self.assertEqual(q.parallele_conseille(24576), 5)
        self.assertEqual(q.parallele_conseille(1000), 1)


class LeMenu(unittest.TestCase):
    """La fiche d'une VM est ce que le menu enverrait."""

    @classmethod
    def setUpClass(cls):
        from script.qemu import deploy_qemu

        cls.todo = todo()
        cls.deploy = deploy_qemu

    def fiche(self, *combo):
        return q.fiche(self.todo, self.deploy, combo, "ldesk", "$6$x$y")

    def test_deploy_command_is_the_menus(self):
        f = self.fiche("fedora", "44", "plasma")
        argv = f["deploiement"]
        self.assertEqual(argv[:2], ["sudo", "-n"])
        self.assertTrue(argv[2].endswith("script/qemu/deploy_qemu.py"))
        self.assertIn("--desktop=plasma", argv)
        self.assertEqual(argv[argv.index("--desktop-remote") + 1], "krdp")
        self.assertEqual(argv[argv.index("--password-hash") + 1], "$6$x$y")
        self.assertEqual(argv[-1], "--no-git-identity")
        self.assertIn("-y", argv)

    def test_remote_command_is_the_menus_desktop_only_path(self):
        f = self.fiche("debian", "12", "xfce")
        self.assertEqual(
            f["distante"],
            self.todo._qemu_erplibre_remote_cmd(
                None, desktop="xfce", distro="debian", version="12"
            ),
        )

    def test_krdp_before_6_8_goes_tls(self):
        self.assertEqual(
            self.fiche("rocky", "10", "plasma")["securite"], "/sec:tls"
        )
        self.assertEqual(
            self.fiche("nixos", "26.05", "plasma")["securite"], "/sec:tls"
        )
        self.assertEqual(self.fiche("fedora", "44", "plasma")["securite"], "-")

    def test_faillock_only_for_krdp_on_fedora_and_el(self):
        self.assertTrue(self.fiche("almalinux", "10", "plasma")["faillock"])
        self.assertFalse(self.fiche("arch", "latest", "plasma")["faillock"])
        self.assertFalse(self.fiche("fedora", "44", "xfce")["faillock"])

    def test_gnome_receives_the_password_the_menu_way(self):
        self.assertTrue(
            self.fiche("fedora", "44", "gnome")["mot_de_passe_dans_vm"]
        )
        self.assertFalse(
            self.fiche("fedora", "44", "xfce")["mot_de_passe_dans_vm"]
        )

    def test_tigervnc_port_on_arch(self):
        f = self.fiche("arch", "latest", "xfce")
        self.assertEqual((f["genre"], f["port"]), ("x11", 5901))

    def test_timezone_and_locale_are_the_forms(self):
        """Le fuseau de l'hôte par la méthode du menu, la locale par défaut
        de deploy_qemu.py, tous deux écrits dans la commande."""
        f = self.fiche("fedora", "44", "xfce")
        argv = f["deploiement"]
        fuseau = self.todo._qemu_host_timezone()
        locale = self.deploy.build_parser().get_default("locale")
        self.assertEqual(argv[argv.index("--timezone") + 1], fuseau)
        self.assertEqual(argv[argv.index("--locale") + 1], locale)
        self.assertEqual((f["fuseau"], f["locale"]), (fuseau, locale))
        donne = q.fiche(
            self.todo,
            self.deploy,
            ("fedora", "44", "xfce"),
            "ldesk",
            "$6$x$y",
            ("Etc/GMT+5", "C.UTF-8"),
        )["deploiement"]
        self.assertEqual(donne[donne.index("--timezone") + 1], "Etc/GMT+5")
        self.assertEqual(donne[donne.index("--locale") + 1], "C.UTF-8")


class LectureInvite(unittest.TestCase):
    SONDE = "\n".join(
        [
            "== dm",
            "sddm.service",
            "active",
            "== failed",
            "mcelog.service loaded failed failed Machine Check",
            "tuned-ppd.service loaded failed failed Profiles",
            "== sessions",
            "1 Name=erplibre Type=wayland Class=user Seat=seat0 State=active"
            " LockedHint=yes Service=sddm-autologin ",
            "c1 Name=sddm Type=x11 Class=greeter Seat=seat0 State=closing"
            " LockedHint=no Service=sddm-greeter ",
            "4 Name=erplibre Type=tty Class=user Seat= State=active"
            " LockedHint=no Service=sshd ",
            "== ps",
            "root     /usr/sbin/sshd -D",
            "erplibre bash -c pgrep -u erplibre -f xfce4-session",
            "erplibre /run/current-system/sw/bin/.xfce4-session-wrapped",
            "lightdm  /usr/bin/i3",
            "== listen",
            'LISTEN 0 50 *:3389 *:* users:(("xrdp",pid=812,fd=11))',
            'LISTEN 0 128 [::]:22 [::]:* users:(("sshd",pid=1,fd=4))',
            "== motd",
            "  client RDP sur localhost:3390, ...:3389",
        ]
    )

    def setUp(self):
        self.s = q.sections(self.SONDE)

    def test_sections(self):
        self.assertEqual(self.s["dm"], ["sddm.service", "active"])
        self.assertEqual(len(self.s["ps"]), 4)

    def test_failed_units(self):
        self.assertEqual(
            q.unites_en_echec(self.s["failed"]),
            ["mcelog.service", "tuned-ppd.service"],
        )

    def test_autologin_session(self):
        auto = q.ouverture_auto(q.sessions(self.s["sessions"]))
        self.assertEqual(auto["LockedHint"], "yes")
        self.assertEqual(auto["Service"], "sddm-autologin")
        # La seule session ssh du compte n'est pas une ouverture automatique.
        self.assertIsNone(
            q.ouverture_auto(q.sessions([self.s["sessions"][2]]))
        )

    def test_listening_ports_and_processes(self):
        ports = q.ecoutes(self.s["listen"])
        self.assertEqual(ports[3389], {"xrdp"})
        self.assertIn(22, ports)

    def test_process_matched_by_executable_not_command_line(self):
        ps = self.s["ps"]
        self.assertTrue(
            q.processus_present(ps, ("xfce4-session",), "erplibre")
        )
        # i3 tourne, mais pas sous le compte : le gestionnaire d'affichage.
        self.assertFalse(q.processus_present(ps, ("i3",), "erplibre"))
        self.assertTrue(q.processus_present(ps, ("i3",)))
        # Le shell qui porte « xfce4-session » en argument ne compte pas.
        seul_shell = [ps[1]]
        self.assertFalse(
            q.processus_present(seul_shell, ("xfce4-session",), "erplibre")
        )

    def test_effective_access(self):
        ports = q.ecoutes(self.s["listen"])
        self.assertEqual(q.acces_effectif("grd", "apt", ports), "xrdp")
        self.assertEqual(q.acces_effectif("grd", "dnf", {}), "grd")
        self.assertEqual(q.acces_effectif("x11", "pacman", {}), "tigervnc")
        self.assertEqual(q.acces_effectif("x11", "zypper", {}), "xrdp")
        self.assertEqual(q.acces_effectif("krdp", "dnf", ports), "krdp")


class Journaux(unittest.TestCase):
    def test_install_warnings(self):
        texte = "ok\n   ⚠ xrdp absent\n"
        self.assertEqual(q.avertissements(texte, "apt"), (1, 0))

    def test_nixos_rc4_excused_only_for_its_cause(self):
        texte = (
            "Failed to reload dbus-broker.service\n"
            "   ⚠ nixos-rebuild switch a rendu 4\n"
            "   ⚠ autre chose\n"
        )
        self.assertEqual(q.avertissements(texte, "nix"), (1, 1))
        sans_cause = texte.replace("dbus-broker", "sshd")
        self.assertEqual(q.avertissements(sans_cause, "nix"), (2, 0))
        self.assertEqual(q.avertissements(texte, "apt"), (2, 0))

    def test_pam_failures_without_polkit_noise(self):
        texte = "\n".join(
            [
                "xrdp-sesman: pam_unix(xrdp-sesman:auth): authentication"
                " failure; logname= uid=0",
                "polkitd: authentication-agent-1 Failed to register",
                "krdpserver: Invalid username or password",
            ]
        )
        self.assertEqual(q.echecs_pam(texte), 2)


class Verdict(unittest.TestCase):
    def test_green(self):
        self.assertEqual(q.verdict(vert_krdp()), ([], []))

    def test_each_defect_fails(self):
        defauts = {
            "deploy": "1 30s",
            "cloud_final": "failed",
            "install": "1 31s",
            "install_warn": "2",
            "reboot_ssh": "FAIL",
            "ip_after": "192.0.2.11",
            "dm": "sddm.service inactive",
            "failed_units": "tuned-ppd.service",
            "autologin": "no",
            "locked": "no",
            "port_listen": "3389 fermé",
            "motd_port": "MISSING-3389",
            "console_shot": "ERROR refused",
            "rdp_good": "alive=0 rc=1",
            "rdp_good_pam": "1",
            "rdp_bad_pam": "0",
            "rdp_good_img": "colours=8 nonblack=0.10",
            "faillock_good_after": "alive=0 rc=1",
            "done": "0",
            "vm_password": "FAIL",
        }
        for cle, valeur in defauts.items():
            with self.subTest(cle=cle):
                raisons, _notes = q.verdict(vert_krdp(**{cle: valeur}))
                self.assertTrue(raisons, cle)

    def test_missing_image_fails(self):
        r = vert_krdp()
        del r["rdp_good_img"]
        self.assertTrue(q.verdict(r)[0])

    def test_mcelog_excused_and_said(self):
        raisons, notes = q.verdict(vert_krdp(failed_units="mcelog.service"))
        self.assertEqual(raisons, [])
        self.assertTrue(any("mcelog" in n for n in notes))
        raisons, _ = q.verdict(
            vert_krdp(failed_units="mcelog.service,tuned-ppd.service")
        )
        self.assertEqual(len(raisons), 1)
        self.assertIn("tuned-ppd", raisons[0])

    def test_nixos_rc4_note(self):
        raisons, notes = q.verdict(vert_krdp(install_warn_nix_rc4="1"))
        self.assertEqual(raisons, [])
        self.assertTrue(notes)

    def test_expected_flat_image_only_for_leap16_i3(self):
        base = dict(
            kind="x11",
            access="xrdp",
            distro="opensuse",
            version="16.0",
            flavour="i3",
            xsess="running",
            rdp_good_img="colours=16 nonblack=0.04",
            autologin="no",
            locked="no",
        )
        raisons, notes = q.verdict(vert_krdp(**base))
        self.assertEqual(raisons, [])
        self.assertTrue(any("i3status" in n for n in notes))
        base["version"] = "tumbleweed"
        self.assertTrue(q.verdict(vert_krdp(**base))[0])

    def test_grd_auth_only(self):
        r = vert_krdp(
            kind="grd", access="grd", rdp_good="rc=0", rdp_bad="rc=1"
        )
        self.assertEqual(q.verdict(r)[0], [])
        r["rdp_bad"] = "rc=0"
        self.assertIn("mauvais mot de passe accepté", q.verdict(r)[0])

    def test_xrdp_needs_its_session_process(self):
        r = vert_krdp(kind="x11", access="xrdp", xsess="ABSENT")
        self.assertTrue(q.verdict(r)[0])
        r["xsess"] = "running"
        self.assertEqual(q.verdict(r)[0], [])

    def test_wayvnc_needs_hyprlock_and_vencrypt(self):
        r = vert_krdp(
            kind="wayvnc",
            access="wayvnc",
            port="5900",
            hyprlock="running",
            locked="no",
            vnc_good="saved 1280 800",
            vnc_good_img="colours=36 nonblack=100.00",
            vnc_bad="AUTH-FAIL bad",
        )
        self.assertEqual(q.verdict(r)[0], [])
        for cle, valeur in (
            ("hyprlock", "ABSENT"),
            ("vnc_bad", "saved 1280 800"),
            ("vnc_good", "ERROR no X509Plain"),
        ):
            with self.subTest(cle=cle):
                self.assertTrue(q.verdict(dict(r, **{cle: valeur}))[0])
        # L'écran de hyprlock est un fond uni : une teinte reste verte.
        uni = dict(r, vnc_good_img="colours=1 nonblack=100.00")
        self.assertEqual(q.verdict(uni)[0], [])

    def test_tigervnc_unit(self):
        r = vert_krdp(
            kind="x11",
            access="tigervnc",
            port="5901",
            vnc_unit="active",
            vnc_good="saved 1024 768",
            vnc_good_img="colours=5000 nonblack=99.99",
            vnc_bad="AUTH-FAIL",
            xsess="running",
        )
        self.assertEqual(q.verdict(r)[0], [])
        self.assertTrue(q.verdict(dict(r, vnc_unit="inactive"))[0])

    def test_vnc_image_judged_like_rdp(self):
        """L'image TigerVNC du bon mot de passe suit la règle des teintes de
        RDP ; celle de wayvnc (hyprlock, fond uni) ne s'y juge pas ; la
        console QEMU est notée, jamais jugée."""
        for genre, port in (("tigervnc", "5901"),):
            r = vert_krdp(
                kind="wayvnc" if genre == "wayvnc" else "x11",
                access=genre,
                port=port,
                hyprlock="running",
                locked="no",
                vnc_unit="active",
                xsess="running",
                vnc_good="saved 1280 800",
                vnc_good_img=f"colours={q.TEINTES_MIN} nonblack=100.00",
                vnc_bad="AUTH-FAIL",
                console_img="colours=1 nonblack=0.00",
            )
            with self.subTest(genre=genre):
                self.assertEqual(q.verdict(r)[0], [])
                plat = dict(
                    r, vnc_good_img=f"colours={q.TEINTES_MIN - 1} nonblack=1"
                )
                self.assertIn("image VNC plate", q.verdict(plat)[0][0])
                sans = dict(r)
                del sans["vnc_good_img"]
                self.assertTrue(q.verdict(sans)[0])
                # Capture manquée : une seule raison, pas deux.
                rate = dict(sans, vnc_good="ERROR refused")
                self.assertEqual(len(q.verdict(rate)[0]), 1)

    def test_failed_units_and_ip_change_stay_strict(self):
        """Toute unité en échec hors EXCUSES_UNITES et toute adresse changée
        au redémarrage font échouer la VM, même seules."""
        raisons, _ = q.verdict(vert_krdp(failed_units="tuned-ppd.service"))
        self.assertEqual(raisons, ["unités en échec : tuned-ppd.service"])
        raisons, _ = q.verdict(vert_krdp(ip_after="192.0.2.11"))
        self.assertEqual(len(raisons), 1)
        self.assertIn("adresse changée", raisons[0])

    def test_abandon_hides_checks_that_never_ran(self):
        r = {
            "kind": "krdp",
            "deploy": "1 20s",
            "abandon": "déploiement rc=1",
            "done": "1",
        }
        raisons, _ = q.verdict(r)
        self.assertEqual(len(raisons), 2)

    def test_not_started(self):
        self.assertEqual(q.verdict({}), (["non commencée"], []))

    def test_summary_table(self):
        lignes, verts = q.bilan(
            {"a": vert_krdp(), "b": vert_krdp(dm="x failed")}
        )
        self.assertEqual(verts, 1)
        self.assertEqual(lignes[-1], "1/2 OK")
        self.assertIn("FAIL", lignes[1])


class Images(unittest.TestCase):
    def test_png_roundtrip_and_colours(self):
        rgb = bytes([0, 0, 0] * 3 + [200, 10, 10])
        donnees = img.png_octets(2, 2, rgb)
        self.assertEqual(img.png_lire(donnees), (2, 2, rgb))
        n, pct = img.teintes(2, 2, rgb)
        self.assertEqual((n, pct), (2, 25.0))

    def test_colours_capped(self):
        rgb = b"".join(bytes((i % 256, i // 256, 7)) for i in range(6000))
        self.assertEqual(img.teintes(6000, 1, rgb)[0], img.TEINTES_MAX)

    def test_png_refuses_other_filters(self):
        donnees = bytearray(img.png_octets(1, 1, b"\x01\x02\x03"))
        brut = zlib.compress(b"\x01\x01\x02\x03")
        debut = donnees.index(b"IDAT") - 4
        fin = debut + 12 + struct.unpack(">I", donnees[debut : debut + 4])[0]
        donnees[debut:fin] = img._bloc(b"IDAT", brut)
        with self.assertRaises(ValueError):
            img.png_lire(bytes(donnees))

    def test_xwd_zpixmap_32(self):
        largeur, hauteur = 2, 1
        entete = [0] * 25
        entete[0], entete[2], entete[4], entete[5] = 100, 2, largeur, hauteur
        entete[11], entete[12] = 32, 8
        pixels = bytes([1, 2, 3, 0, 250, 251, 252, 0])  # B, G, R, X
        donnees = struct.pack(">25I", *entete) + pixels
        self.assertEqual(
            img.xwd_vers_rgb(donnees), (2, 1, bytes([3, 2, 1, 252, 251, 250]))
        )
        entete[11] = 16
        with self.assertRaises(ValueError):
            img.xwd_vers_rgb(struct.pack(">25I", *entete) + pixels)

    def test_security_choice(self):
        self.assertEqual(img.choisir_securite([1, 2], None), 1)
        self.assertEqual(img.choisir_securite([2, 19], "erplibre"), 19)
        # Un serveur de bureau qui n'offre pas VeNCrypt n'est pas celui
        # que le guide annonce : pas de repli sur None ni sur VNC auth.
        with self.assertRaises(ValueError):
            img.choisir_securite([1, 2], "erplibre")
        self.assertEqual(img.choisir_sous_type([256, 259, 262]), 262)
        with self.assertRaises(ValueError):
            img.choisir_sous_type([256, 257])

    def test_rfb_capture_from_a_real_socket(self):
        serveur = socket.socket()
        serveur.bind(("127.0.0.1", 0))
        serveur.listen(1)
        port = serveur.getsockname()[1]

        def servir():
            c, _ = serveur.accept()
            c.sendall(b"RFB 003.008\n")
            c.recv(12)
            c.sendall(bytes([1, 1]))  # un type : None
            c.recv(1)
            c.sendall(struct.pack(">I", 0))
            c.recv(1)
            c.sendall(struct.pack(">HH", 2, 1) + b"\0" * 16)
            c.sendall(struct.pack(">I", 4) + b"test")
            c.recv(20)
            c.recv(8)
            c.recv(10)
            c.sendall(struct.pack(">BxH", 0, 1))
            c.sendall(struct.pack(">HHHHi", 0, 0, 2, 1, 0))
            c.sendall(bytes([10, 20, 30, 0, 0, 0, 0, 0]))
            c.close()

        fil = threading.Thread(target=servir, daemon=True)
        fil.start()
        with tempfile.TemporaryDirectory() as d:
            sortie = os.path.join(d, "c.png")
            etat = img.capture_rfb("127.0.0.1", port, sortie)
            self.assertEqual(etat, "saved 2 1")
            self.assertEqual(img.stat_png(sortie), "colours=2 nonblack=50.00")
        fil.join(5)
        serveur.close()


def xwd_riche(chemin, largeur=64, hauteur=8):
    """Une capture XWD de `largeur` × `hauteur` pixels tous différents."""
    entete = [0] * 25
    entete[0], entete[2], entete[4], entete[5] = 100, 2, largeur, hauteur
    entete[11], entete[12] = 32, 4 * largeur
    pixels = b"".join(
        bytes((i % 256, (7 * i) % 256, 200, 0))
        for i in range(largeur * hauteur)
    )
    with open(chemin, "wb") as fh:
        fh.write(struct.pack(">25I", *entete) + pixels)


class InviteSimule:
    """Répond aux commandes d'un essai comme une VM KRdp ou xrdp verte."""

    def __init__(self, essai_dossier, genre):
        self.dossier = essai_dossier
        self.genre = genre
        self.boots = iter(["boot-a", "boot-a", "boot-b"] + ["boot-b"] * 50)
        self.vues = []

    def sonde(self):
        if self.genre == "krdp":
            session = (
                "1 Name=erplibre Type=wayland Class=user Seat=seat0"
                " State=active LockedHint=yes Service=plasmalogin-autologin"
            )
            ecoute = 'LISTEN 0 50 *:3389 *:* users:(("krdpserver",pid=9,fd=1))'
        else:
            session = (
                "c1 Name=lightdm Type=x11 Class=greeter Seat=seat0"
                " State=active LockedHint=no Service=lightdm-greeter"
            )
            ecoute = 'LISTEN 0 50 *:3389 *:* users:(("xrdp",pid=9,fd=1))'
        return "\n".join(
            [
                "== dm",
                "x.service",
                "active",
                "== failed",
                "mcelog.service loaded failed failed MCE",
                "== sessions",
                session,
                "== ps",
                "erplibre /usr/bin/xfce4-session",
                "== listen",
                ecoute,
                "== motd",
                "client RDP :3389",
            ]
        )

    def __call__(self, argv, delai, entree=None, sortie=None, env=None):
        self.vues.append(argv)
        texte = ""
        if argv[0] == "virsh":
            texte = {"domuuid": "u-1", "vncdisplay": "127.0.0.1:3"}.get(
                argv[3], ""
            )
        elif argv[0] == "podman":
            etiquette = argv[argv.index("/rdp.sh") + 1]
            if etiquette.startswith("good"):
                xwd_riche(os.path.join(self.dossier, f"rdp_{etiquette}.xwd"))
                texte = "alive=1"
            else:
                texte = "alive=0 rc=1"
        elif argv[0] == "ssh":
            cmd = argv[-1]
            if "boot_id" in cmd:
                texte = next(self.boots)
            elif cmd == "bash -s":
                texte = self.sonde()
            elif "cloud-final" in cmd:
                texte = "active"
            elif cmd.startswith("date"):
                texte = "1000"
            elif cmd.startswith("ps "):
                texte = "erplibre /usr/bin/xfce4-session"
        if sortie:
            with open(sortie, "a") as fh:
                fh.write("ok\n")
            return 0, ""
        return 0, texte


class EssaiSimule(unittest.TestCase):
    """Le déroulé d'un essai, invité et hôte simulés : chaque étape
    s'enchaîne, note ses clés, et le verdict d'une VM saine est vert."""

    def mener(self, combo):
        from script.qemu import deploy_qemu

        f = q.fiche(todo(), deploy_qemu, combo, "ldesk", "$6$x$y")
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d))
        invite = InviteSimule(os.path.join(d, f["nom"]), f["genre"])

        def capture(hote, port, sortie, utilisateur=None, mdp=None, **_k):
            if utilisateur and mdp != q.MOT_DE_PASSE:
                return "AUTH-FAIL"
            img.png_ecrire(sortie, 2, 1, bytes([1, 2, 3, 200, 100, 50]))
            return "saved 2 1"

        faux_todo = mock.Mock()
        faux_todo._qemu_vm_ip.return_value = "192.0.2.20"
        ctx = {
            "journal": os.path.join(d, "j.log"),
            "arret": threading.Event(),
            "garder": False,
            "todo": faux_todo,
            "noter_uuid": mock.Mock(),
            "mots_de_passe": d,
        }
        with contextlib.ExitStack() as pile:
            for patch in (
                mock.patch.object(q, "lancer", invite),
                mock.patch.object(q.time, "sleep"),
                mock.patch.object(q.image, "capture_rfb", capture),
                mock.patch("sys.stdout"),
            ):
                pile.enter_context(patch)
            essai = q.Essai(f, d, ctx)
            essai.journal_depuis = lambda depuis, etiquette: (
                0 if etiquette in ("good", "after") else 1
            )
            r = essai.mener()
        with open(os.path.join(d, f["nom"], "result.txt")) as fh:
            self.assertEqual(q.lire_resultat(fh.read()), r)
        ctx["noter_uuid"].assert_called_once_with(f["nom"], "u-1")
        return r, invite

    def test_krdp_fedora_with_faillock(self):
        r, invite = self.mener(("fedora", "44", "plasma"))
        self.assertEqual(q.verdict(r)[0], [], r)
        self.assertEqual(r["access"], "krdp")
        self.assertEqual(r["reboot_ssh"], "ok")
        self.assertEqual(r["ip_after"], r["ip"])
        self.assertEqual(r["destroyed"], "yes")
        self.assertIn("faillock_good_after", r)
        self.assertGreaterEqual(q.lire_teintes(r["rdp_good_img"]), 32)
        podman = [v for v in invite.vues if v[0] == "podman"]
        self.assertEqual(len(podman), 7)  # bad, good, 4 échecs, good_after

    def test_xrdp_debian(self):
        r, _invite = self.mener(("debian", "13", "xfce"))
        self.assertEqual(q.verdict(r)[0], [], r)
        self.assertEqual((r["access"], r["xsess"]), ("xrdp", "running"))

    def test_reboot_needs_a_new_boot_id(self):
        r, invite = self.mener(("debian", "13", "xfce"))
        boots = [v for v in invite.vues if "boot_id" in v[-1]]
        self.assertGreaterEqual(len(boots), 3)


class ImageClient(unittest.TestCase):
    """L'image du client RDP : base épinglée, reconstruite quand son
    Containerfile change ou qu'on le demande."""

    def test_base_image_pinned_to_a_dated_tag(self):
        import re

        lignes = (CLIENT / "Containerfile").read_text().splitlines()
        base = [x for x in lignes if x.startswith("FROM ")]
        self.assertEqual(len(base), 1)
        self.assertRegex(
            base[0],
            r"^FROM docker\.io/library/archlinux:base-\d{8}\.0\.\d+$",
        )
        self.assertFalse(re.search(r":latest\b", base[0]))

    def test_build_command_labels_and_forces(self):
        argv = q.commande_construction("abc", False)
        self.assertEqual(argv[:2], ["podman", "build"])
        self.assertNotIn("--no-cache", argv)
        self.assertEqual(
            argv[argv.index("--label") + 1], f"{q.ETIQUETTE_CLIENT}=abc"
        )
        self.assertEqual(argv[argv.index("-t") + 1], q.IMAGE_CLIENT)
        self.assertIn("--no-cache", q.commande_construction("abc", True))

    def preparer(self, etiquette, reconstruire=False):
        vues = []

        def lancer(argv, delai, **_k):
            vues.append(argv)
            if argv[1:3] == ["image", "inspect"]:
                return (0, etiquette + "\n") if etiquette else (125, "")
            return 0, ""

        with mock.patch.object(q, "lancer", lancer), mock.patch("sys.stdout"):
            self.assertTrue(q.preparer_client(reconstruire, None))
        return [v for v in vues if v[1] == "build"]

    def test_kept_only_when_built_from_this_containerfile(self):
        actuelle = q.empreinte_containerfile()
        self.assertEqual(self.preparer(actuelle), [])
        for etiquette in ("", "<no value>", "0" * 64):
            with self.subTest(etiquette=etiquette):
                builds = self.preparer(etiquette)
                self.assertEqual(len(builds), 1)
                self.assertIn(f"{q.ETIQUETTE_CLIENT}={actuelle}", builds[0])
                self.assertNotIn("--no-cache", builds[0])

    def test_rebuild_option_rebuilds_without_cache(self):
        builds = self.preparer(q.empreinte_containerfile(), reconstruire=True)
        self.assertEqual(len(builds), 1)
        self.assertIn("--no-cache", builds[0])
        args = q.analyser(["--reconstruire-client"])[1]
        self.assertTrue(args.reconstruire_client)


class MenuEtVerrou(unittest.TestCase):
    """Le test des bureaux s'offre dans le menu des tests longs, se défait
    avec les autres, et le verrou commun le voit tourner."""

    def setUp(self):
        from script.todo.todo import TODO

        self.todo = TODO.__new__(TODO)

    def choisir(self, choix, reponses):
        from script.todo import longtest_menu

        with (
            mock.patch.object(
                longtest_menu.click, "prompt", side_effect=[choix, "0"]
            ),
            mock.patch("builtins.input", side_effect=reponses),
            mock.patch.object(self.todo, "fill_help_info", return_value=""),
            mock.patch.object(self.todo, "_longtest_run") as run,
            mock.patch("builtins.print"),
        ):
            self.todo.prompt_execute_longtest()
        return run.call_args_list

    def test_plan_entry_is_a_dry_run_of_the_chosen_part(self):
        appels = self.choisir("10", ["plasma, xfce", "fedora"])
        self.assertEqual(len(appels), 1)
        script, args = appels[0].args
        self.assertEqual(script, "qemu_desktops.py")
        self.assertEqual(
            args, "--dry-run --saveurs 'plasma, xfce' --distros fedora"
        )
        self.assertEqual(
            q.analyser(["--dry-run", "--saveurs", "plasma, xfce"])[1].saveurs,
            "plasma, xfce",
        )

    def test_run_entry_creates_and_blank_means_whole_matrix(self):
        appels = self.choisir("11", ["", ""])
        self.assertEqual(appels[0].args, ("qemu_desktops.py", ""))

    def test_undo_entry_still_undoes(self):
        with mock.patch.object(self.todo, "_longtest_defaire") as defaire:
            self.choisir("12", [])
        defaire.assert_called_once_with()

    def test_labels_translated(self):
        from script.todo.todo_i18n import TRANSLATIONS

        for cle in (
            "Desktop matrix: plan only (dry-run)",
            "Desktop matrix: run it",
            "Desktop flavours (comma-separated, blank = all): ",
            "Distributions (comma-separated, blank = all): ",
        ):
            with self.subTest(cle=cle):
                self.assertIn(cle, TRANSLATIONS)
                self.assertTrue(TRANSLATIONS[cle]["fr"])

    def test_undone_with_the_other_long_tests(self):
        import descente

        from script.todo.longtest_menu import SCRIPTS_DEFAISABLES

        self.assertIn(q.SCRIPT, SCRIPTS_DEFAISABLES)
        self.assertIn(q.SCRIPT, descente.SCRIPTS)

    def test_the_common_lock_sees_a_running_desktop_run(self):
        """Une course des bureaux vivante fait refuser leur « --detruire »
        aux autres tests longs : le verrou la reconnaît à son argument."""
        import subprocess

        import descente

        with tempfile.TemporaryDirectory() as d:
            faux = os.path.join(d, q.SCRIPT)
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)", faux]
            )
            try:
                # Juste après le fork, /proc/PID/cmdline est encore vide.
                cmdline = f"/proc/{proc.pid}/cmdline"
                for _i in range(100):
                    with open(cmdline, "rb") as fh:
                        if q.SCRIPT.encode() in fh.read():
                            break
                    time.sleep(0.05)
                self.assertTrue(descente.descente_vivante(proc.pid))
                self.assertIn(proc.pid, descente.autre_descente())
            finally:
                proc.kill()
                proc.wait()


class Lancer(unittest.TestCase):
    def test_no_input_means_dev_null_not_the_terminal(self):
        # Quatre ssh en parallèle qui hériteraient de l'entrée standard
        # liraient le terminal de l'opérateur : chacun reçoit /dev/null.
        lecture, ecriture = os.pipe()
        os.write(ecriture, b"frappe")
        os.close(ecriture)
        sauve = os.dup(0)
        os.dup2(lecture, 0)
        try:
            code, texte = q.lancer(
                [
                    sys.executable,
                    "-c",
                    "import sys; print(len(sys.stdin.read()))",
                ],
                30,
            )
        finally:
            os.dup2(sauve, 0)
            os.close(sauve)
            os.close(lecture)
        self.assertEqual((code, texte.strip()), (0, "0"))
        code, texte = q.lancer(
            [sys.executable, "-c", "import sys; print(sys.stdin.read())"],
            30,
            entree="donnee",
        )
        self.assertEqual(texte.strip(), "donnee")

    def test_timeout_is_124(self):
        code, _texte = q.lancer(
            [sys.executable, "-c", "import time; time.sleep(5)"], 0.3
        )
        self.assertEqual(code, 124)


class Cli(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self.dossier.cleanup)
        for patch in (
            mock.patch.object(q, "DOSSIER", self.dossier.name),
            mock.patch("sys.stdout"),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_prefix_guard(self):
        for mauvais in ("", "a", "LDESK", "l-d"):
            with self.subTest(prefixe=mauvais):
                with mock.patch("sys.stderr"):
                    with self.assertRaises(SystemExit):
                        q.analyser(["--prefixe", mauvais])

    @mock.patch.object(q, "lancer")
    def test_dry_run_creates_nothing(self, lancer):
        argv = ["--dry-run", "--saveurs", "i3", "--distros", "arch"]
        self.assertEqual(q.main(argv), 0)
        lancer.assert_not_called()

    def test_bilan_exit_code(self):
        d = self.dossier.name
        for nom in ("a", "b"):
            os.makedirs(os.path.join(d, nom))
            with open(os.path.join(d, nom, "result.txt"), "w") as fh:
                fh.write("\n".join(f"{k}={v}" for k, v in vert_krdp().items()))
        self.assertEqual(q.main(["--bilan", d]), 0)
        with open(os.path.join(d, "b", "result.txt"), "a") as fh:
            fh.write("\ndm=gdm.service failed\n")
        self.assertEqual(q.main(["--bilan", d]), 1)

    @mock.patch.object(q, "lancer", return_value=(0, ""))
    @mock.patch.object(q, "uuid_de", return_value="u-2")
    def test_destroy_checks_the_uuid(self, _uuid, lancer):
        self.assertIn("rien touché", q.detruire_vm("ldesk-x", "u-1"))
        lancer.assert_not_called()
        self.assertEqual(q.detruire_vm("ldesk-x", "u-2"), "yes")

    @mock.patch("builtins.input", return_value="non")
    @mock.patch.object(q, "detruire_vm")
    @mock.patch.object(q, "domaines", return_value=["ldesk-a"])
    @mock.patch.object(q, "autres_courses", return_value=[])
    def test_destroy_asks_first(self, _autres, _domaines, detruire_vm, _in):
        self.assertEqual(q.detruire("ldesk", None), 1)
        detruire_vm.assert_not_called()

    @mock.patch.object(q, "detruire_vm")
    @mock.patch.object(q, "autres_courses", return_value=[4242])
    def test_destroy_refused_while_a_run_is_alive(self, _autres, detruire_vm):
        self.assertEqual(q.detruire("ldesk", None), 1)
        detruire_vm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
