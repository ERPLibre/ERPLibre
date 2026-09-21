#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La sauvegarde vérifiée existe AILLEURS que sur la machine qui l'a faite.

CE QUE LE DÉPÔT PROMETTAIT SANS LE TENIR. « backup-target » est dans le
SOCLE des destinations de sortie — le jeu que toute posture bornée nomme —
avec son port et sa raison : « La cible des sauvegardes. L'ouvrir en sortie
est ce qui permet de sauvegarder sans monter le disque de la machine sur
l'hôte. » Le pare-feu de « VM paranoid » ouvrait donc déjà cette porte, et
il n'y avait rien derrière.

CE QUI SE VÉRIFIE À DISTANCE, ET CE QUI NE SE VÉRIFIE PAS. Les cinq
contrôles du vérificateur sont du Python : les rejouer là-bas demanderait
d'y pousser du code. Ce qui se prouve honnêtement est que les OCTETS sont
arrivés entiers — une empreinte des deux côtés, et la taille. Le témoin
consigne donc « déposée, empreinte identique », jamais « saine là-bas ».

Ni réseau ni machine : le transport est injecté.
"""

import hashlib
import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.database import backup_ship as S  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402


class Transport:
    """Un transport de banc : il note ce qu'on lui demande et répond."""

    def __init__(self, reponses=None):
        self.appels = []
        self.reponses = list(reponses or [])

    def __call__(self, host, remote, timeout=120, entree=None):
        self.appels.append((host, remote, entree))
        if self.reponses:
            return self.reponses.pop(0)
        return 0, ""


FICHE = {"name": "nas", "target": "sauvegarde@203.0.113.9"}

CIBLE = {
    "name": "nas",
    "kind": "backup-ssh",
    "target": "sauvegarde@203.0.113.9",
    "path": "/tank/erplibre",
}


class TestOuLArchiveSePose(unittest.TestCase):
    def test_the_remote_path_joins_the_target_path_and_the_name(self):
        self.assertEqual(
            "/tank/erplibre/base.zip", S.remote_path(CIBLE, "base.zip")
        )

    def test_a_name_that_climbs_is_refused(self):
        """Un « ../ » écrirait hors du répertoire que la cible a donné."""
        for nom in ("../ailleurs.zip", "a/../../b.zip", "/absolu.zip"):
            with self.subTest(nom=nom):
                with self.assertRaises(ValueError):
                    S.remote_path(CIBLE, nom)

    def test_a_target_without_a_path_is_refused(self):
        with self.assertRaises(ValueError):
            S.remote_path(dict(CIBLE, path=""), "base.zip")


class TestCeQuiSeVerifieLaBas(unittest.TestCase):
    def test_the_fingerprint_is_the_one_the_tool_prints(self):
        """`sha256sum` rend « <empreinte>  <chemin> » : n'en garder que le
        premier mot, sinon la comparaison porte sur le chemin."""
        self.assertEqual(
            "abc123", S.parse_fingerprint("abc123  /tank/erplibre/base.zip")
        )

    def test_an_empty_answer_is_nothing_read(self):
        """Rien lu n'est pas « empreinte différente » : l'un dit qu'on n'a
        pas pu regarder, et les confondre ferait passer une panne de
        transport pour une archive corrompue."""
        self.assertIsNone(S.parse_fingerprint(""))
        self.assertIsNone(S.parse_fingerprint("   \n "))

    def test_a_local_fingerprint_is_the_sha256_of_the_bytes(self):
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as fichier:
            fichier.write(b"des octets")
            chemin = fichier.name
        try:
            self.assertEqual(
                hashlib.sha256(b"des octets").hexdigest(),
                S.local_fingerprint(chemin),
            )
        finally:
            os.unlink(chemin)


class TestLeVerdictDuDepot(unittest.TestCase):
    """Trois réponses, et les confondre est tout le sujet."""

    def test_the_vocabulary_is_closed(self):
        self.assertEqual(
            (S.SHIPPED, S.MISMATCH, S.UNREACHABLE, S.REFUSED), S.VERDICTS
        )

    def test_identical_fingerprints_are_the_only_success(self):
        self.assertEqual(S.SHIPPED, S.compare("abc", "abc"))

    def test_different_fingerprints_are_a_mismatch(self):
        self.assertEqual(S.MISMATCH, S.compare("abc", "def"))

    def test_nothing_read_is_not_a_mismatch(self):
        self.assertEqual(S.UNREACHABLE, S.compare("abc", None))


class TestLeNomFinalNeParaitQueComplet(unittest.TestCase):
    """Une redirection CRÉE le fichier avant le premier octet.

    Le transport coupé en route laissait donc, chez la cible hors-site,
    une archive TRONQUÉE portant le nom exact d'une sauvegarde légitime —
    au seul endroit où l'on ira chercher une sauvegarde le jour où l'on
    en a besoin. Aucun des contrôles locaux ne se rejoue là-bas ; rien
    n'aurait distingué ce fichier d'un bon.

    Le nom définitif n'apparaît désormais qu'au bout : l'archive voyage
    sous un nom de travail, son empreinte est comparée SOUS ce nom, et le
    renommage ne vient qu'après. Un renommage dans le même répertoire est
    atomique — il n'y a pas d'instant où le nom final désigne un fichier
    incomplet.
    """

    def setUp(self):
        import tempfile

        self.archive = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        self.archive.write(b"des octets de sauvegarde")
        self.archive.close()
        self.addCleanup(os.unlink, self.archive.name)
        self.empreinte = hashlib.sha256(
            b"des octets de sauvegarde"
        ).hexdigest()

    def deposer(self, reponses):
        transport = Transport(reponses)
        rendu = S.ship(
            CIBLE,
            FICHE,
            self.archive.name,
            "base.zip",
            run=transport,
            ask=lambda _invite: "",
        )
        return rendu, transport

    @staticmethod
    def commandes(transport):
        return [remote for _h, remote, _e in transport.appels]

    def test_the_payload_never_travels_under_the_final_name(self):
        _rendu, transport = self.deposer(
            [(1, "test: absent"), (0, ""), (0, f"{'a' * 64}  x"), (0, "")]
        )
        envoi = [c for c in self.commandes(transport) if "cat >" in c]
        self.assertEqual(1, len(envoi))
        self.assertNotIn("/tank/erplibre/base.zip'", envoi[0])
        self.assertIn(S.SUFFIXE_PARTIEL, envoi[0])

    def test_a_cut_transport_leaves_nothing_behind(self):
        """Le nom de travail est retiré : le laisser ferait échouer la
        reprise sur une garde de collision, pour un fichier mort."""
        rendu, transport = self.deposer([(1, "test: absent"), (255, "coupé")])
        self.assertEqual(S.UNREACHABLE, rendu.verdict)
        retraits = [c for c in self.commandes(transport) if "rm -f" in c]
        self.assertEqual(1, len(retraits))
        self.assertIn(S.SUFFIXE_PARTIEL, retraits[0])

    def test_a_mismatch_never_takes_the_final_name(self):
        """Un contenu qui diffère est un contenu qu'on ne veut pas relire
        un jour de panne, et surtout pas sous un nom rassurant."""
        rendu, transport = self.deposer(
            [(1, "test: absent"), (0, ""), (0, f"{'b' * 64}  x")]
        )
        self.assertEqual(S.MISMATCH, rendu.verdict)
        self.assertEqual(
            [], [c for c in self.commandes(transport) if "mv " in c]
        )
        self.assertTrue(any("rm -f" in c for c in self.commandes(transport)))

    def test_only_a_proven_payload_is_renamed(self):
        empreinte = self.empreinte
        rendu, transport = self.deposer(
            [(1, "test: absent"), (0, ""), (0, f"{empreinte}  x"), (0, "")]
        )
        self.assertEqual(S.SHIPPED, rendu.verdict)
        renommages = [c for c in self.commandes(transport) if "mv " in c]
        self.assertEqual(1, len(renommages))
        self.assertIn(S.SUFFIXE_PARTIEL, renommages[0])
        self.assertIn("base.zip", renommages[0])

    def test_a_rename_that_fails_is_not_a_success(self):
        """Le contenu est bon et pourtant il n'est pas à sa place : dire
        « déposé » enverrait chercher un fichier qui n'existe pas."""
        empreinte = self.empreinte
        rendu, _t = self.deposer(
            [
                (1, "test: absent"),
                (0, ""),
                (0, f"{empreinte}  x"),
                (1, "mv: refus"),
            ]
        )
        self.assertNotEqual(S.SHIPPED, rendu.verdict)


class TestLeDepot(unittest.TestCase):
    """Déposer, puis relire ce qui est arrivé."""

    def setUp(self):
        import tempfile

        self.archive = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        self.archive.write(b"des octets de sauvegarde")
        self.archive.close()
        self.addCleanup(os.unlink, self.archive.name)
        self.empreinte = hashlib.sha256(
            b"des octets de sauvegarde"
        ).hexdigest()

    def deposer(self, reponses, retape=None):
        transport = Transport(reponses)
        rendu = S.ship(
            CIBLE,
            FICHE,
            self.archive.name,
            "base.zip",
            run=transport,
            ask=lambda _invite: retape if retape is not None else "",
        )
        return rendu, transport

    def test_a_free_name_ships_and_reads_back(self):
        rendu, transport = self.deposer(
            [
                (1, ""),
                (0, ""),
                (0, f"{self.empreinte}  /tank/erplibre/base.zip"),
            ]
        )
        self.assertEqual(S.SHIPPED, rendu.verdict)
        # LES GESTES, et non leur nombre : compter fige une étape de plus
        # ou de moins, là où le contrat est « on regarde, on envoie, on
        # relit, on renomme » — et le renommage est arrivé après coup.
        gestes = [remote for _h, remote, _e in transport.appels]
        self.assertTrue(any("cat >" in g for g in gestes))
        self.assertTrue(any("sha256" in g or "shasum" in g for g in gestes))
        self.assertTrue(any(g.startswith("mv ") for g in gestes))

    def test_the_payload_travels_on_the_standard_input(self):
        """Un envoi composé à côté perdrait le privilège, le délai et le
        dépouillement du bruit ssh que le transport tient déjà."""
        _rendu, transport = self.deposer(
            [(1, ""), (0, ""), (0, f"{self.empreinte}  x")]
        )
        _host, remote, entree = transport.appels[1]
        self.assertIsNotNone(entree)
        self.assertIn("cat >", remote)

    def test_the_payload_is_born_owner_only(self):
        """C'est un dump de PRODUCTION. Le dépôt se donne déjà ce mal pour
        le simple témoin ; la charge vaut au moins autant."""
        _rendu, transport = self.deposer(
            [(1, ""), (0, ""), (0, f"{self.empreinte}  x")]
        )
        self.assertIn("umask 0077", transport.appels[1][1])

    def test_different_bytes_at_the_far_end_are_a_mismatch(self):
        rendu, _t = self.deposer([(1, ""), (0, ""), (0, "autre  x")])
        self.assertEqual(S.MISMATCH, rendu.verdict)

    def test_a_target_that_says_nothing_is_not_a_mismatch(self):
        rendu, _t = self.deposer([(1, ""), (0, ""), (255, "timeout")])
        self.assertEqual(S.UNREACHABLE, rendu.verdict)

    def test_a_failed_send_never_pretends_to_read_back(self):
        rendu, transport = self.deposer([(1, ""), (255, "timeout")])
        self.assertEqual(S.UNREACHABLE, rendu.verdict)
        gestes = [remote for _h, remote, _e in transport.appels]
        # RIEN N'EST RELU : lire une empreinte après un envoi mort rendrait
        # « rien lu », qui se lit comme un transport en panne alors que
        # c'est l'envoi qui n'a pas eu lieu.
        self.assertEqual([], [g for g in gestes if "sha256" in g])
        # …et le nom de travail est retiré.
        self.assertTrue(any("rm -f" in g for g in gestes))

    def test_a_name_that_climbs_is_refused_before_anything(self):
        transport = Transport()
        rendu = S.ship(
            CIBLE, FICHE, self.archive.name, "../ailleurs.zip", run=transport
        )
        self.assertEqual(S.REFUSED, rendu.verdict)
        self.assertEqual([], transport.appels)


class TestLaCollisionSeQuestionne(TestLeDepot):
    """Écraser une archive est destructeur, et le nom se retape.

    Le nom par défaut porte déjà la date à la seconde : une collision est
    donc un nom tapé à la main ou un renvoi du même fichier — jamais un
    hasard, et toujours une décision.
    """

    def test_an_existing_archive_is_named_and_asks_for_the_name(self):
        rendu, transport = self.deposer([(0, "")], retape="autre")
        self.assertEqual(S.REFUSED, rendu.verdict)
        self.assertEqual(1, len(transport.appels))
        self.assertIn("base.zip", rendu.detail)

    def test_retyping_the_name_overwrites(self):
        rendu, transport = self.deposer(
            [(0, ""), (0, ""), (0, f"{self.empreinte}  x")], retape="base.zip"
        )
        self.assertEqual(S.SHIPPED, rendu.verdict)
        # LES GESTES, et non leur nombre : compter fige une étape de plus
        # ou de moins, là où le contrat est « on regarde, on envoie, on
        # relit, on renomme » — et le renommage est arrivé après coup.
        gestes = [remote for _h, remote, _e in transport.appels]
        self.assertTrue(any("cat >" in g for g in gestes))
        self.assertTrue(any("sha256" in g or "shasum" in g for g in gestes))
        self.assertTrue(any(g.startswith("mv ") for g in gestes))

    def test_a_free_name_asks_nothing(self):
        demandes = []
        transport = Transport([(1, ""), (0, ""), (0, f"{self.empreinte}  x")])
        S.ship(
            CIBLE,
            FICHE,
            self.archive.name,
            "base.zip",
            run=transport,
            ask=lambda invite: demandes.append(invite) or "",
        )
        self.assertEqual([], demandes)


class TestLeMenuDeSauvegardeDeposeEnsuite(unittest.TestCase):
    """Ce que la sauvegarde fait APRÈS avoir été vérifiée ici.

    « backup-target » est dans le SOCLE des destinations, avec son port et
    sa raison, et rien ne le remplissait : le pare-feu d'une VM confinée
    ouvrait cette porte sur le vide.
    """

    def setUp(self):
        import sys as _sys
        import tempfile

        _sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        self.todo = TODO.__new__(TODO)
        self.archive = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        self.archive.write(b"x")
        self.archive.close()
        self.addCleanup(os.unlink, self.archive.name)

    def constat(self, sain=True):
        from script.database import backup_verify

        return backup_verify.Verification(
            backup_verify.SOUND if sain else "truncated",
            path=self.archive.name,
            size=1,
            checks=(),
        )

    def deposer(self, cibles, sain=True):
        import io as tampon_io
        from contextlib import redirect_stdout
        from unittest import mock

        from script.database import backup_ship
        from script.remote import deploy_target

        tampon = tampon_io.StringIO()
        with mock.patch.object(deploy_target, "load_all", return_value=cibles):
            with mock.patch.object(
                backup_ship,
                "ship",
                return_value=backup_ship.Shipping(
                    backup_ship.SHIPPED, "", "la"
                ),
            ) as depot:
                with redirect_stdout(tampon):
                    self.todo.db_manager = (
                        self.todo.db_manager
                        if hasattr(self.todo, "db_manager")
                        else None
                    )
                    from script.todo.database_manager import DatabaseManager

                    gestionnaire = DatabaseManager(None, None)
                    gestionnaire._backup_ship(
                        self.constat(sain), self.archive.name, "base.zip"
                    )
        return tampon.getvalue(), depot

    def test_no_target_says_so_once_and_names_where_to_make_one(self):
        ecran, depot = self.deposer([])
        self.assertFalse(depot.called)
        self.assertIn(t("No backup target is configured."), ecran)
        self.assertIn(t("Deployment targets"), ecran)

    def test_a_backup_target_receives_the_archive(self):
        cible = {
            "name": "nas",
            "kind": "backup-ssh",
            "target": "a@203.0.113.9",
            "path": "/tank",
        }
        _ecran, depot = self.deposer([cible])
        self.assertTrue(depot.called)

    def test_a_deployment_target_is_not_a_backup_target(self):
        """Les confondre enverrait le dump sur la machine de production."""
        cible = {
            "name": "prod",
            "kind": "erplibre-ssh",
            "target": "a@203.0.113.9",
            "path": "/opt",
        }
        _ecran, depot = self.deposer([cible])
        self.assertFalse(depot.called)

    def test_the_backup_entry_reaches_the_shipping(self):
        """La couture ne sert à rien si l'écran ne la traverse pas."""
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "database_manager.py")
        arbre = ast.parse(open(chemin, encoding="utf-8").read())
        corps = [
            n
            for n in ast.walk(arbre)
            if isinstance(n, ast.FunctionDef)
            and n.name == "create_backup_from_database"
        ]
        self.assertEqual(1, len(corps))
        appels = [
            n.func.attr
            for n in ast.walk(corps[0])
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        ]
        self.assertIn("verify_and_witness", appels)
        self.assertIn("_backup_ship", appels)

    def test_an_archive_that_did_not_pass_here_is_not_sent(self):
        """Déposer ailleurs une archive qu'on sait abîmée remplirait la
        cible de copies inutilisables, et ferait croire à une sauvegarde."""
        cible = {
            "name": "nas",
            "kind": "backup-ssh",
            "target": "a@203.0.113.9",
            "path": "/tank",
        }
        _ecran, depot = self.deposer([cible], sain=False)
        self.assertFalse(depot.called)


if __name__ == "__main__":
    unittest.main()
