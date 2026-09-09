#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La lecture des baux dnsmasq : jamais une invite de mot de passe.

Ce que ces tests défendent n'est pas une fonctionnalité, c'est une
ABSENCE. Le chemin lisait les baux par « sudo sh -c cat », sans jamais
demander s'il en avait besoin. Or il est appelé une fois par VM pour
afficher une liste, et toutes les trois secondes pendant dix minutes par
l'attente d'une VM : l'invite de mot de passe root tombait donc au milieu
d'un écran, en boucle, et entraînait à taper un mot de passe root dans ce
qui le demande. C'est l'habitude qui coûte, pas l'appel.

Trois règles en sortent, et chacune a son test.

La lecture directe passe d'abord, et elle suffit sur une installation
standard : ces fichiers d'état sont en lecture pour tous, contrairement au
« .conf » posé à côté. Le privilège n'est tenté qu'ensuite, et seulement
avec « -n », qui échoue au lieu de demander. Et un répertoire interdit rend
un glob VIDE, indistinguable de « aucun réseau » — d'où l'essai privilégié
même sans chemin trouvé.

Les adresses sont INVENTÉES, comme l'exige la règle du dépôt pour tout
exemple qui illustre un interdit : 192.168.199.x ne paraît nulle part
ailleurs.
"""

import unittest
from unittest import mock

from script.todo.qemu_manage import DNSMASQ_STATUS, lease_status_text

BAIL = (
    '{"ip-address":"192.168.199.24","mac-address":"52:54:00:aa:bb:cc",'
    '"hostname":"machine-un","expiry-time":1788000000}'
)
BAIL_AUTRE = (
    '{"ip-address":"192.168.199.31","mac-address":"52:54:00:dd:ee:ff",'
    '"hostname":"machine-deux","expiry-time":1788000001}'
)


class Appels:
    """Un exécuteur qui note ce qu'on lui a demandé de lancer."""

    def __init__(self, stdout="", leve=None):
        self.stdout = stdout
        self.leve = leve
        self.argvs = []

    def __call__(self, argv, **kwargs):
        self.argvs.append(argv)
        if self.leve:
            raise self.leve
        return mock.Mock(stdout=self.stdout, returncode=0)


class TestLectureDirecte(unittest.TestCase):
    def test_direct_read_wins(self):
        run = Appels(stdout="ne doit pas servir")
        texte = lease_status_text(
            paths=lambda motif: ["/a.status", "/b.status"],
            read=lambda chemin: BAIL if chemin == "/a.status" else BAIL_AUTRE,
            run=run,
            euid=lambda: 1000,
        )
        self.assertIn("192.168.199.24", texte)
        self.assertIn("192.168.199.31", texte)
        self.assertEqual(run.argvs, [], "aucun privilège n'était nécessaire")

    def test_readable_but_empty_does_not_escalate(self):
        """Un réseau sans bail rend un fichier VIDE, pas une interdiction.

        Escalader ici lancerait un sudo par VM sur toute machine dont le
        réseau libvirt n'a encore servi aucun bail."""
        run = Appels(stdout=BAIL)
        texte = lease_status_text(
            paths=lambda motif: ["/virbr0.status"],
            read=lambda chemin: "",
            run=run,
            euid=lambda: 1000,
        )
        self.assertEqual(texte, "")
        self.assertEqual(run.argvs, [])

    def test_paths_are_sorted(self):
        """L'ordre de lecture ne dépend pas de celui du système de fichiers."""
        lus = []

        def read(chemin):
            lus.append(chemin)
            return ""

        lease_status_text(
            paths=lambda motif: ["/z.status", "/a.status"],
            read=read,
            run=Appels(),
            euid=lambda: 1000,
        )
        self.assertEqual(lus, ["/a.status", "/z.status"])


class TestReplisPrivilegies(unittest.TestCase):
    def test_unreadable_file_escalates(self):
        run = Appels(stdout=BAIL)
        texte = lease_status_text(
            paths=lambda motif: ["/a.status"],
            read=mock.Mock(side_effect=PermissionError(13, "refusé")),
            run=run,
            euid=lambda: 1000,
        )
        self.assertIn("192.168.199.24", texte)
        self.assertEqual(len(run.argvs), 1)

    def test_empty_glob_escalates(self):
        """Un répertoire interdit rend un glob vide, non une erreur."""
        run = Appels(stdout=BAIL)
        texte = lease_status_text(
            paths=lambda motif: [],
            read=lambda chemin: "",
            run=run,
            euid=lambda: 1000,
        )
        self.assertIn("192.168.199.24", texte)

    def test_sudo_is_never_interactive(self):
        """« -n » suit « sudo » immédiatement : sudo échoue au lieu de demander.

        C'est la seule assertion de ce fichier qui porte sur la FORME de
        l'argv, et elle le fait parce que l'ordre compte : « sudo sh -c … -n »
        passerait le drapeau au shell, pas à sudo."""
        run = Appels(stdout="")
        lease_status_text(
            paths=lambda motif: [],
            read=lambda chemin: "",
            run=run,
            euid=lambda: 1000,
        )
        argv = run.argvs[0]
        self.assertEqual(argv[0], "sudo")
        self.assertEqual(argv[1], "-n")
        self.assertIn(DNSMASQ_STATUS, " ".join(argv))

    def test_root_does_not_escalate(self):
        """Root a déjà tout vu : sudo n'y changerait rien."""
        run = Appels(stdout=BAIL)
        texte = lease_status_text(
            paths=lambda motif: [],
            read=lambda chemin: "",
            run=run,
            euid=lambda: 0,
        )
        self.assertEqual(texte, "")
        self.assertEqual(run.argvs, [])

    def test_sudo_absent_returns_empty(self):
        texte = lease_status_text(
            paths=lambda motif: [],
            read=lambda chemin: "",
            run=Appels(leve=FileNotFoundError(2, "sudo")),
            euid=lambda: 1000,
        )
        self.assertEqual(texte, "")

    def test_sudo_refusal_returns_empty(self):
        """« sudo -n » sans droit rend un code non nul et un stdout vide."""
        texte = lease_status_text(
            paths=lambda motif: [],
            read=lambda chemin: "",
            run=lambda argv, **kw: mock.Mock(stdout="", returncode=1),
            euid=lambda: 1000,
        )
        self.assertEqual(texte, "")


class TestBailParHostname(unittest.TestCase):
    """Le parcours qui consomme le texte, pour que le repli reste vrai."""

    def _chercher(self, texte, nom, candidates):
        from script.todo import qemu_manage

        with mock.patch.object(
            qemu_manage, "lease_status_text", return_value=texte
        ):
            return qemu_manage.QemuManageMixin._qemu_lease_ip_for_host(
                nom, candidates
            )

    def test_the_lease_naming_the_vm_wins(self):
        trouve = self._chercher(
            BAIL + BAIL_AUTRE,
            "machine-deux",
            ["192.168.199.24", "192.168.199.31"],
        )
        self.assertEqual(trouve, "192.168.199.31")

    def test_a_lease_outside_the_candidates_is_ignored(self):
        """Un bail périmé nomme la VM sans être une candidate joignable."""
        trouve = self._chercher(BAIL, "machine-un", ["192.168.199.99"])
        self.assertIsNone(trouve)

    def test_no_readable_lease_returns_none(self):
        """Le cas du privilège refusé : None, et l'appelant se replie."""
        self.assertIsNone(self._chercher("", "machine-un", ["192.168.199.24"]))


if __name__ == "__main__":
    unittest.main()
