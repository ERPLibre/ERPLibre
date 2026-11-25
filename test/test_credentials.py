#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""script/lib_ops/credentials.py : credentials systemd d'une unité.

La version de systemd et `systemd-creds` sont joués par des lanceurs
fabriqués : aucun systemctl ni systemd-creds réel n'est appelé. Les
dossiers `/etc/credstore*` sont des dossiers temporaires. Seul
`systemd.lancer_entree` lance un vrai processus, l'interpréteur de ce
test, pour vérifier que l'entrée standard porte les octets donnés.

Données inventées : unité `erplibre-backup-demo_db.service`, secret
`secret-invente-0042`.
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.lib_ops import credentials, service, systemd  # noqa: E402

UNITE = "erplibre-backup-demo_db.service"
SECRET = b"secret-invente-0042\n"


def setUpModule():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from profil_isole import profil_isole

    profil_isole()


def lanceur_de(table):
    """Un lanceur qui répond depuis `table` ({premier mot: (code,
    sortie)}) et note chaque argv."""
    appels = []

    def lanceur(argv, timeout=60):
        appels.append(list(argv))
        return table.get(" ".join(argv[:2]), (127, "absent"))

    lanceur.appels = appels
    return lanceur


class TestVersion(unittest.TestCase):
    def test_lecture(self):
        for sortie, attendue in (
            ("systemd 259 (259.9-1)\n+PAM +AUDIT\n", 259),
            ("systemd 245 (245.4-4ubuntu3.24)\n", 245),
            ("  systemd 252 (252.39-1~deb12u1)\n", 252),
            ("rien de reconnaissable\n", None),
            ("", None),
            ("libsystemd 255\n", None),
        ):
            with self.subTest(sortie=sortie):
                lanceur = lanceur_de({"systemctl --version": (0, sortie)})
                self.assertEqual(systemd.version(lanceur), attendue)
                self.assertEqual(lanceur.appels, [["systemctl", "--version"]])

    def test_echec(self):
        lanceur = lanceur_de({"systemctl --version": (1, "systemd 259")})
        self.assertIsNone(systemd.version(lanceur))

    def test_detecter(self):
        lanceur = lanceur_de(
            {
                "systemctl --version": (0, "systemd 252 (252.1)\n"),
                "systemd-creds --version": (0, "systemd 252\n"),
            }
        )
        self.assertEqual(credentials.detecter(lanceur), (252, True))
        lanceur = lanceur_de({"systemctl --version": (0, "systemd 249\n")})
        self.assertEqual(credentials.detecter(lanceur), (249, False))

    def test_detecter_seul_127_dit_absent(self):
        for version, code, attendu in (
            ("systemd 255\n", 127, (255, False)),
            ("systemd 249\n", 1, (249, False)),
            ("inconnu\n", 124, (None, False)),
        ):
            with self.subTest(version=version, code=code):
                lanceur = lanceur_de(
                    {
                        "systemctl --version": (0, version),
                        "systemd-creds --version": (code, "x"),
                    }
                )
                self.assertEqual(credentials.detecter(lanceur), attendu)
        for code in (124, 1, 126):
            with self.subTest(code=code):
                lanceur = lanceur_de(
                    {
                        "systemctl --version": (0, "systemd 255\n"),
                        "systemd-creds --version": (code, "délai"),
                    }
                )
                with self.assertRaises(credentials.ErreurCredential) as err:
                    credentials.detecter(lanceur)
                self.assertIn(f"code {code}", str(err.exception))


class TestStockage(unittest.TestCase):
    """Texte d'unité selon la version : 250 et plus chiffré, 247 à 249 ou
    sans systemd-creds en clair, avant 247 refusé."""

    def test_par_version(self):
        for version, creds, chiffre in (
            (247, True, False),
            (249, True, False),
            (250, True, True),
            (259, True, True),
            (259, False, False),
        ):
            with self.subTest(version=version, creds=creds):
                stockage = credentials.choisir_stockage(version, creds)
                self.assertEqual(stockage.chiffre, chiffre)
                ligne = credentials.ligne_unite(
                    stockage, UNITE, "warmup.api_key"
                )
                if chiffre:
                    self.assertEqual(
                        ligne,
                        "LoadCredentialEncrypted=warmup.api_key:"
                        f"/etc/credstore.encrypted/{UNITE}.warmup.api_key",
                    )
                else:
                    self.assertEqual(
                        ligne,
                        "LoadCredential=warmup.api_key:"
                        f"/etc/credstore/{UNITE}.warmup.api_key",
                    )

    def test_refus(self):
        for version in (246, 219, None):
            with self.subTest(version=version):
                with self.assertRaises(credentials.ErreurCredential) as err:
                    credentials.choisir_stockage(version, True)
                if version is not None:
                    self.assertIn(str(version), str(err.exception))
                self.assertIn("247", str(err.exception))

    def test_nom(self):
        for nom in ("warmup.api_key", "backup-x", "a_b"):
            self.assertTrue(credentials.nom_valide(nom))
        for nom in ("", ".", "..", "a:b", "a/b", "a b", "é"):
            self.assertFalse(credentials.nom_valide(nom), nom)


class TestLignesCitees(unittest.TestCase):
    def test_seuls_les_chemins_de_l_unite_sous_credstore(self):
        texte = "\n".join(
            [
                "[Service]",
                f"LoadCredential=a:/etc/credstore/{UNITE}.a",
                f"LoadCredentialEncrypted=b:/etc/credstore.encrypted/{UNITE}.b",
                "LoadCredential=c:/etc/credstore/autre.service.c",
                f"LoadCredential=d:/etc/ailleurs/{UNITE}.d",
                f"LoadCredential=e:/etc/credstore/sous/{UNITE}.e",
                f"LoadCredential=f:/etc/credstore/../credstore/{UNITE}.f",
                f"LoadCredential=g:/etc/credstore/{UNITE}.",
                f"# LoadCredential=h:/etc/credstore/{UNITE}.h",
                f"LoadCredential=a:/etc/credstore/{UNITE}.a",
                "ExecStart=/bin/true",
            ]
        )
        self.assertEqual(
            credentials.chemins_a_retirer(texte, UNITE),
            [
                f"/etc/credstore/{UNITE}.a",
                f"/etc/credstore.encrypted/{UNITE}.b",
            ],
        )
        self.assertEqual(credentials.chemins_a_retirer("", UNITE), [])


class BaseDossier(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.bac = os.path.realpath(d.name)


class TestEcriture(BaseDossier):
    def test_dossier_et_fichier_en_clair(self):
        ancien = os.umask(0)
        self.addCleanup(os.umask, ancien)
        dossier = os.path.join(self.bac, "etc", "credstore")
        credentials.preparer_dossier(dossier)
        self.assertEqual(os.stat(dossier).st_mode & 0o777, 0o700)
        final = os.path.join(dossier, f"{UNITE}.a")
        credentials.ecrire_clair(final, SECRET)
        with open(final, "rb") as f:
            self.assertEqual(f.read(), SECRET)
        self.assertEqual(os.stat(final).st_mode & 0o777, 0o600)
        self.assertEqual(os.listdir(dossier), [f"{UNITE}.a"])
        # Une réécriture remplace le fichier, sans reste.
        credentials.ecrire_clair(final, b"autre")
        with open(final, "rb") as f:
            self.assertEqual(f.read(), b"autre")
        self.assertEqual(os.listdir(dossier), [f"{UNITE}.a"])

    def test_dossier_refuse(self):
        ouvert = os.path.join(self.bac, "ouvert")
        os.mkdir(ouvert)
        os.chmod(ouvert, 0o755)
        lien = os.path.join(self.bac, "lien")
        os.symlink(ouvert, lien)
        fichier = os.path.join(self.bac, "fichier")
        open(fichier, "w").close()
        for chemin in (ouvert, lien, fichier):
            with self.subTest(chemin=chemin):
                with self.assertRaises(credentials.ErreurCredential):
                    credentials.preparer_dossier(chemin)
        ferme = os.path.join(self.bac, "ferme")
        os.mkdir(ferme, 0o700)
        os.chmod(ferme, 0o700)
        credentials.preparer_dossier(ferme)


class TestChiffrement(BaseDossier):
    def setUp(self):
        super().setUp()
        self.dossier = os.path.join(self.bac, "credstore.encrypted")
        credentials.preparer_dossier(self.dossier)
        self.final = os.path.join(self.dossier, f"{UNITE}.warmup.api_key")
        self.entrees = []

    def lanceur_entree(self, code=0):
        def lanceur(argv, donnees, timeout=60):
            self.entrees.append((list(argv), donnees))
            if code:
                with open(argv[-1], "wb") as f:
                    f.write(b"partiel")
                return code, "refus simulé"
            with open(argv[-1], "wb") as f:
                f.write(b"CHIFFRE-INVENTE")
            return 0, ""

        return lanceur

    def test_secret_sur_l_entree_standard(self):
        credentials.chiffrer(
            self.final, "warmup.api_key", SECRET, self.lanceur_entree()
        )
        [(argv, donnees)] = self.entrees
        self.assertEqual(donnees, SECRET)
        self.assertEqual(
            argv[:5],
            [
                "systemd-creds",
                "encrypt",
                "--name=warmup.api_key",
                "--with-key=host",
                "-",
            ],
        )
        self.assertNotIn(SECRET.decode().strip(), " ".join(argv))
        # La sortie temporaire est DANS le dossier du credential.
        self.assertEqual(
            os.path.dirname(os.path.dirname(argv[-1])), self.dossier
        )
        with open(self.final, "rb") as f:
            self.assertEqual(f.read(), b"CHIFFRE-INVENTE")
        self.assertEqual(os.stat(self.final).st_mode & 0o777, 0o600)
        self.assertEqual(
            os.listdir(self.dossier), [os.path.basename(self.final)]
        )

    def test_echec_ne_laisse_rien(self):
        with self.assertRaises(credentials.ErreurCredential) as err:
            credentials.chiffrer(
                self.final, "warmup.api_key", SECRET, self.lanceur_entree(1)
            )
        self.assertNotIn(SECRET.decode().strip(), str(err.exception))
        self.assertEqual(os.listdir(self.dossier), [])


class TestFichiersDeLUnite(BaseDossier):
    def test_noms_exacts_et_restes(self):
        self.assertEqual(
            credentials.fichiers_de_l_unite(UNITE, ["a", "x:y"]),
            [
                f"/etc/credstore/{UNITE}.a",
                f"/etc/credstore.encrypted/{UNITE}.a",
            ],
        )
        final = os.path.join(self.bac, f"{UNITE}.a")
        prefixe = credentials.prefixe_provisoire(final)
        self.assertEqual(prefixe, f".{UNITE}.a~")
        for nom in (
            prefixe + "k3j",
            f".{UNITE}.a.b~k3j",
            f".{UNITE}.a",
            f"{UNITE}.a",
        ):
            open(os.path.join(self.bac, nom), "w").close()
        self.assertEqual(
            credentials.restes(self.bac, [f"{UNITE}.a"]),
            [os.path.join(self.bac, prefixe + "k3j")],
        )
        self.assertEqual(
            credentials.restes(os.path.join(self.bac, "absent"), ["x"]), []
        )

    def test_present(self):
        self.assertTrue(credentials.present(self.bac))
        self.assertFalse(credentials.present(os.path.join(self.bac, "absent")))
        if os.geteuid() != 0:
            ferme = os.path.join(self.bac, "ferme")
            os.mkdir(ferme, 0)
            self.addCleanup(os.chmod, ferme, 0o700)
            self.assertIsNone(credentials.present(os.path.join(ferme, "x")))


class TestLectureDuSecret(BaseDossier):
    def test_lecture(self):
        source = os.path.join(self.bac, "cle")
        with open(source, "wb") as f:
            f.write(SECRET)
        self.assertEqual(credentials.lire_secret(source), SECRET)

    def test_refus_sans_citer_le_contenu(self):
        source = os.path.join(self.bac, "cle")
        with open(source, "wb") as f:
            f.write(SECRET)
        lien = os.path.join(self.bac, "lien")
        os.symlink(source, lien)
        vide = os.path.join(self.bac, "vide")
        with open(vide, "wb") as f:
            f.write(b"  \n")
        gros = os.path.join(self.bac, "gros")
        with open(gros, "wb") as f:
            f.write(b"x" * (credentials.TAILLE_MAX + 1))
        # Un tube nommé sans écrivain : refusé, sans attendre.
        tube = os.path.join(self.bac, "tube")
        os.mkfifo(tube, 0o600)
        for chemin in (lien, vide, gros, tube, self.bac, source + ".absent"):
            with self.subTest(chemin=chemin):
                with self.assertRaises(credentials.ErreurCredential) as err:
                    credentials.lire_secret(chemin)
                self.assertNotIn(SECRET.decode().strip(), str(err.exception))


class TestLectureCoteOutil(BaseDossier):
    """`fichier` : credential de l'unité, puis option, puis chemin du
    profil, puis rien."""

    def setUp(self):
        super().setUp()
        self.dossier = os.path.join(self.bac, "creds")
        os.mkdir(self.dossier)
        self.credential = os.path.join(self.dossier, "warmup.api_key")
        with open(self.credential, "wb") as f:
            f.write(SECRET)
        self.environ = {"CREDENTIALS_DIRECTORY": self.dossier}

    def test_ordre(self):
        f = credentials.fichier
        self.assertEqual(
            f("warmup.api_key", "/srv/opt", "/srv/profil", self.environ),
            (self.credential, "systemd"),
        )
        self.assertEqual(
            f("warmup.api_key", "/srv/opt", "/srv/profil", {}),
            ("/srv/opt", "cli"),
        )
        self.assertEqual(
            f("warmup.api_key", None, "/srv/profil", {}),
            ("/srv/profil", "profil"),
        )
        self.assertEqual(f("warmup.api_key", None, None, {}), (None, None))
        # Une référence KeePass du profil n'est jamais lue.
        self.assertEqual(
            f("warmup.api_key", None, {"kdbx": "ERPLibre/x"}, {}),
            (None, None),
        )
        # Un autre nom n'est pas fourni par l'unité.
        self.assertEqual(
            f("backup.exemple", None, "/srv/profil", self.environ),
            ("/srv/profil", "profil"),
        )

    def test_credential_non_regulier_ignore(self):
        os.remove(self.credential)
        os.symlink(os.path.join(self.bac, "ailleurs"), self.credential)
        self.assertIsNone(
            credentials.disponible("warmup.api_key", self.environ)
        )
        os.remove(self.credential)
        os.mkdir(self.credential)
        self.assertIsNone(
            credentials.disponible("warmup.api_key", self.environ)
        )
        self.assertIsNone(credentials.disponible("../creds", self.environ))

    def test_environnement_du_processus_par_defaut(self):
        with mock.patch.dict(os.environ, self.environ):
            self.assertEqual(
                credentials.disponible("warmup.api_key"), self.credential
            )
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(credentials.disponible("warmup.api_key"))


class TestLanceurEntree(unittest.TestCase):
    def test_entree_standard_et_sortie(self):
        code, sortie = systemd.lancer_entree(
            [
                sys.executable,
                "-c",
                "import sys; d = sys.stdin.buffer.read();"
                " print(len(d), d == b'secret-invente-0042\\n')",
            ],
            SECRET,
            30,
        )
        self.assertEqual(code, 0)
        self.assertEqual(sortie.strip(), f"{len(SECRET)} True")

    def test_absent_et_echec(self):
        code, _sortie = systemd.lancer_entree(
            ["/nonexistent/erplibre-absent"], b"x", 5
        )
        self.assertEqual(code, 127)
        code, sortie = systemd.lancer_entree(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('refus'); sys.exit(3)",
            ],
            b"",
            30,
        )
        self.assertEqual((code, sortie), (3, "refus"))

    def test_seul_argv_est_trace(self):
        systeme = service.SystemeBase(verbeux=True)
        erreurs = io.StringIO()
        with (
            mock.patch.object(
                systemd, "lancer_entree", return_value=(0, "")
            ) as appel,
            contextlib.redirect_stderr(erreurs),
        ):
            systeme.lanceur_entree(["systemd-creds", "encrypt", "-"], SECRET)
        appel.assert_called_once_with(
            ["systemd-creds", "encrypt", "-"], SECRET, 60
        )
        self.assertIn("systemd-creds encrypt -", erreurs.getvalue())
        self.assertNotIn(SECRET.decode().strip(), erreurs.getvalue())


if __name__ == "__main__":
    unittest.main()
