#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le minuteur qui avance les dépôts de travail d'une forge jusqu'à leurs
miroirs, sans forge : les dépôts nus vivent dans un dossier temporaire et
le push passe par file://, qui exerce le même refus du non-fast-forward
côté client.

Tous les propriétaires, dépôts, comptes et jetons sont inventés.
"""

import ast
import base64
import contextlib
import fcntl
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from script.forgejo import forge_sync as fs

JETON = "0123456789abcdef0123456789abcdef01234567"
SOURCE = Path(fs.__file__)


def paire(depot="org/r", miroir="org-mirror/r", branches=None):
    return {
        "depot": depot,
        "miroir": miroir,
        "branches": branches
        or [{"travail": "main", "miroir": "main", "creer": False}],
    }


class TestValidation(unittest.TestCase):
    def test_forge(self):
        self.assertTrue(fs.forge_valide("http://127.0.0.1:3000"))
        self.assertTrue(fs.forge_valide("http://localhost:3000"))
        for url in (
            "http://192.0.2.1:3000",
            "https://127.0.0.1:3000",
            "http://127.0.0.1:3000/",
            "",
            None,
        ):
            with self.subTest(url=url):
                self.assertFalse(fs.forge_valide(url))
        self.assertTrue(fs.forge_valide("file:///tmp/forge", locale=False))

    def test_une_configuration_valide(self):
        self.assertEqual(
            fs.valider(
                {
                    "version": 1,
                    "paires": [paire(), paire("Org/s", "Org-MIRROR/s")],
                }
            ),
            [],
        )

    def test_les_refus(self):
        cas = {
            "branche -x": paire(
                branches=[{"travail": "-x", "miroir": "main", "creer": False}]
            ),
            "branche a..b": paire(
                branches=[
                    {"travail": "main", "miroir": "a..b", "creer": False}
                ]
            ),
            "branche .lock": paire(
                branches=[{"travail": "a.lock", "miroir": "a", "creer": False}]
            ),
            "branche espace": paire(
                branches=[{"travail": "a b", "miroir": "a", "creer": False}]
            ),
            "creer absent": paire(branches=[{"travail": "a", "miroir": "a"}]),
            "travail doublé": paire(
                branches=[
                    {"travail": "a", "miroir": "a", "creer": False},
                    {"travail": "a", "miroir": "b", "creer": False},
                ]
            ),
            "sans branches": dict(paire(), branches=[]),
            "dépôt ..": paire("org/..", "org-mirror/.."),
            "dépôt .git": paire("org/r.git", "org-mirror/r.git"),
            "traversée": paire("org/a/b", "org-mirror/r"),
            "même propriétaire": paire("Org-mirror/r", "org-MIRROR/r"),
            "dépôt dans -mirror": paire("a-mirror/r", "b-mirror/r"),
            "miroir sans suffixe": paire("org/r", "autre/r"),
        }
        for nom, p in cas.items():
            with self.subTest(nom=nom):
                self.assertNotEqual(
                    fs.valider({"version": 1, "paires": [p]}), []
                )
        self.assertNotEqual(fs.valider({"version": 2, "paires": []}), [])
        self.assertNotEqual(fs.valider(None), [])

    def test_fusionner_et_retirer(self):
        ancienne = {
            "version": 1,
            "paires": [paire("Org/a", "Org-mirror/a"), paire()],
        }
        neuve = paire(
            "ORG/A",
            "Org-mirror/a",
            [{"travail": "x", "miroir": "x", "creer": True}],
        )
        res = fs.fusionner(ancienne, {"version": 1, "paires": [neuve]})
        self.assertEqual(res["paires"], [neuve, paire()])
        self.assertEqual(fs.retirer(res, ["org/a"])["paires"], [paire()])

    def test_chemin_disque(self):
        self.assertEqual(
            fs.chemin_disque("/d", "Org/Repo"),
            os.path.join("/d", "org", "repo.git"),
        )

    def test_lire_environnement(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as fh:
            fh.write(
                "FORGE_SYNC_URL=http://127.0.0.1:3000\n"
                "FORGE_SYNC_REPOS=/d\nFORGE_SYNC_ACCOUNT=fichier\n"
            )
        self.addCleanup(os.unlink, fh.name)
        self.assertEqual(
            fs.lire_environnement(fh.name, {"FORGE_SYNC_ACCOUNT": "env"}),
            {
                "forge": "http://127.0.0.1:3000",
                "depots": "/d",
                "compte": "env",
            },
        )


class TestLeJeton(unittest.TestCase):
    def test_le_jeton_n_est_que_dans_l_en_tete(self):
        forge = "http://127.0.0.1:3000"
        env = fs.environnement(forge, "compte", JETON, "/h")
        self.assertEqual(env["GIT_CONFIG_KEY_0"], f"http.{forge}/.extraHeader")
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        attendu = base64.b64encode(f"compte:{JETON}".encode()).decode()
        self.assertEqual(
            env["GIT_CONFIG_VALUE_0"], f"Authorization: Basic {attendu}"
        )
        porteurs = [k for k, v in env.items() if JETON in v or attendu in v]
        self.assertEqual(porteurs, ["GIT_CONFIG_VALUE_0"])

    def test_masquer(self):
        b64 = base64.b64encode(f"c:{JETON}".encode()).decode()
        self.assertEqual(
            fs.masquer(f"x {JETON} y {b64}", [JETON, b64, ""]), "x *** y ***"
        )

    def test_le_module_n_importe_que_la_bibliotheque_standard(self):
        arbre = ast.parse(SOURCE.read_text(encoding="utf-8"))
        modules = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                modules |= {a.name.split(".")[0] for a in noeud.names}
            elif isinstance(noeud, ast.ImportFrom):
                modules.add((noeud.module or "").split(".")[0])
        self.assertTrue(modules)
        self.assertEqual(modules - set(sys.stdlib_module_names), set())


IDENTITE = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


class Forge:
    """Une fausse forge sur disque : « org/r.git » (travail) et
    « org-mirror/r.git » (miroir), remplis depuis un clone de travail."""

    def __init__(self, racine):
        self.racine = racine
        self.depots = os.path.join(racine, "forge")
        self.forge = "file://" + self.depots
        self.travail = fs.chemin_disque(self.depots, "org/r")
        self.miroir = fs.chemin_disque(self.depots, "org-mirror/r")
        for rep in (self.travail, self.miroir):
            os.makedirs(rep)
            self.git(["init", "-q", "--bare", rep])
        self.clone = os.path.join(racine, "clone")
        self.git(["init", "-q", self.clone])
        self.env = fs.environnement(self.forge, "compte", JETON, racine)

    def git(self, args, cwd=None):
        fini = subprocess.run(
            ["git", *args],
            cwd=cwd or self.racine,
            env=dict(os.environ, **IDENTITE),
            capture_output=True,
            text=True,
        )
        if fini.returncode:
            raise AssertionError(fini.stderr)
        return fini.stdout.strip()

    def commit(self, parent=None, message="c"):
        """Un commit vide sur `parent` (ou une racine) ; rend son SHA."""
        arbre = self.git(
            ["hash-object", "-w", "-t", "tree", os.devnull], self.clone
        )
        args = ["commit-tree", arbre]
        if parent:
            args += ["-p", parent]
        return self.git([*args, "-m", message], self.clone)

    def poser(self, rep, branche, sha):
        """La branche `branche` de `rep` posée sur `sha`, forcée : la mise
        en place du cas, jamais le code exercé."""
        self.git(
            ["push", "-q", "--force", rep, f"{sha}:refs/heads/{branche}"],
            self.clone,
        )

    def pointe(self, rep, branche="main"):
        fini = subprocess.run(
            ["git", "rev-parse", "--verify", "-q", f"refs/heads/{branche}"],
            cwd=rep,
            capture_output=True,
            text=True,
        )
        return fini.stdout.strip()

    def passe_paire(self, p=None, git=fs.git):
        return fs.passe_paire(
            p or paire(), self.forge, self.depots, self.env, git
        )


class TestUnePaire(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.f = Forge(dossier.name)
        self.a = self.f.commit(message="a")

    def un(self, **kw):
        res = self.f.passe_paire(**kw)
        self.assertEqual(len(res), 1)
        return res[0]

    def test_a_jour(self):
        self.f.poser(self.f.miroir, "main", self.a)
        self.f.poser(self.f.travail, "main", self.a)
        r = self.un()
        self.assertEqual(r["etat"], "a_jour")
        self.assertEqual((r["travail"], r["miroir_sha"]), (self.a, self.a))

    def test_le_miroir_en_avance_fait_avancer(self):
        b = self.f.commit(self.a, "b")
        self.f.poser(self.f.miroir, "main", b)
        self.f.poser(self.f.travail, "main", self.a)
        r = self.un()
        self.assertEqual(r["etat"], "avance")
        self.assertEqual(r["detail"], f"{self.a[:12]}..{b[:12]}")
        self.assertEqual(self.f.pointe(self.f.travail), b)

    def test_le_travail_en_avance_reste(self):
        c = self.f.commit(self.a, "c")
        self.f.poser(self.f.miroir, "main", self.a)
        self.f.poser(self.f.travail, "main", c)
        r = self.un()
        self.assertEqual((r["etat"], r["detail"]), ("en_avance", "+1"))
        self.assertEqual(self.f.pointe(self.f.travail), c)

    def test_une_divergence_ne_touche_rien_et_garde_sa_date(self):
        b = self.f.commit(self.a, "b")
        c = self.f.commit(self.a, "c")
        self.f.poser(self.f.miroir, "main", b)
        self.f.poser(self.f.travail, "main", c)
        heures = iter([1000, 1001, 5000, 5001])
        cfg = {"version": 1, "paires": [paire()]}

        def passer(precedent=None):
            return fs.passe(
                cfg,
                self.f.forge,
                self.f.depots,
                "compte",
                JETON,
                self.f.racine,
                precedent=precedent,
                maintenant=lambda: next(heures),
            )

        etat1 = passer()
        r = etat1["resultats"][0]
        self.assertEqual(r["etat"], "divergent")
        self.assertIn("absent from the mirror", r["detail"])
        self.assertEqual(r["depuis"], etat1["debut"])
        self.assertEqual(self.f.pointe(self.f.travail), c)
        etat2 = passer(etat1)
        self.assertNotEqual(etat2["debut"], etat1["debut"])
        self.assertEqual(etat2["resultats"][0]["depuis"], etat1["debut"])

    def test_une_origine_reecrite_diverge_avec_ses_comptes(self):
        b = self.f.commit(self.a, "b")
        b2 = self.f.commit(self.a, "b2")
        # Le miroir a porté b, puis l'origine l'a réécrit en b2 : b reste
        # dans ses objets, sans branche.
        self.f.poser(self.f.miroir, "main", b)
        self.f.poser(self.f.miroir, "main", b2)
        self.f.poser(self.f.travail, "main", b)
        r = self.un()
        self.assertEqual((r["etat"], r["detail"]), ("divergent", "+1/-1"))
        self.assertEqual(self.f.pointe(self.f.travail), b)

    def test_une_branche_absente_ne_se_cree_que_sur_demande(self):
        self.f.poser(self.f.miroir, "feat", self.a)
        self.f.poser(self.f.travail, "main", self.a)
        p = paire(
            branches=[{"travail": "feat", "miroir": "feat", "creer": False}]
        )
        self.assertEqual(self.un(p=p)["etat"], "absente")
        self.assertEqual(self.f.pointe(self.f.travail, "feat"), "")
        p["branches"][0]["creer"] = True
        self.assertEqual(self.un(p=p)["etat"], "creee")
        self.assertEqual(self.f.pointe(self.f.travail, "feat"), self.a)

    def test_un_depot_de_travail_absent_ne_recoit_rien(self):
        self.f.poser(self.f.miroir, "main", self.a)
        appels = []

        def enregistrer(args, cwd, env, delai=fs.DELAI_GIT):
            appels.append(args)
            return fs.git(args, cwd, env, delai)

        p = paire("org/zz", "org-mirror/r")
        r = self.un(p=p, git=enregistrer)
        self.assertEqual(r["etat"], "depot_absent")
        self.assertFalse(any(a[0] == "push" for a in appels))
        self.assertFalse(
            os.path.exists(fs.chemin_disque(self.f.depots, "org/zz"))
        )

    def test_un_miroir_absent_ou_sa_branche_absente(self):
        self.f.poser(self.f.travail, "main", self.a)
        r = self.un(p=paire("org/r", "org-mirror/zz"))
        self.assertEqual(
            (r["etat"], r["detail"]), ("erreur", "mirror repository absent")
        )
        self.assertEqual(self.un()["etat"], "absente_miroir")

    def test_un_hook_qui_refuse(self):
        b = self.f.commit(self.a, "b")
        self.f.poser(self.f.miroir, "main", b)
        self.f.poser(self.f.travail, "main", self.a)
        hook = os.path.join(self.f.travail, "hooks", "pre-receive")
        with open(hook, "w") as fh:
            fh.write("#!/bin/sh\necho refused-by-hook >&2\nexit 1\n")
        os.chmod(hook, 0o755)
        r = self.un()
        self.assertEqual(r["etat"], "refuse")
        self.assertIn("pre-receive hook declined", r["detail"])
        self.assertEqual(self.f.pointe(self.f.travail), self.a)

    def test_le_motif_du_refus_vient_de_la_sortie_porcelain(self):
        """git écrit le motif d'un refus sur la sortie standard ; l'erreur
        finit sur un conseil. Le motif reste masqué."""
        b = self.f.commit(self.a, "b")
        self.f.poser(self.f.miroir, "main", b)
        self.f.poser(self.f.travail, "main", self.a)

        def refuser(args, cwd, env, delai=fs.DELAI_GIT):
            if args[0] != "push":
                return fs.git(args, cwd, env, delai)
            return (
                f"To {self.f.forge}/org/r.git\n"
                f"!\t{b}:refs/heads/main\t[rejected] (fetch first {JETON})\n"
                "Done\n",
                "error: failed to push some refs\n"
                "hint: See the 'Note about fast-forwards'\n",
                1,
            )

        r = fs.passe_paire(
            paire(), self.f.forge, self.f.depots, self.f.env, refuser, (JETON,)
        )[0]
        self.assertEqual(r["etat"], "refuse")
        self.assertEqual(r["detail"], "[rejected] (fetch first ***)")

    def test_le_motif_du_refus_sans_ligne_porcelain(self):
        self.assertEqual(
            fs.motif_refus(
                "",
                "remote: branche protégée\nremote: \nerror: failed to push",
            ),
            "remote: branche protégée",
        )
        self.assertEqual(
            fs.motif_refus("Done\n", "fatal: a\nfatal: b\n"), "fatal: b"
        )

    def test_jamais_de_force_et_le_miroir_intact(self):
        b = self.f.commit(self.a, "b")
        c = self.f.commit(self.a, "c")
        self.f.poser(self.f.miroir, "main", b)
        self.f.poser(self.f.miroir, "feat", b)
        self.f.poser(self.f.travail, "main", self.a)
        self.f.poser(self.f.travail, "feat", c)

        def instantane(rep):
            res = {}
            for racine, _d, fichiers in os.walk(os.path.join(rep, "refs")):
                for nom in fichiers:
                    chemin = os.path.join(racine, nom)
                    res[chemin] = Path(chemin).read_bytes()
            packed = os.path.join(rep, "packed-refs")
            if os.path.exists(packed):
                res[packed] = Path(packed).read_bytes()
            return res

        avant = instantane(self.f.miroir)
        appels = []

        def enregistrer(args, cwd, env, delai=fs.DELAI_GIT):
            appels.append((list(args), cwd))
            return fs.git(args, cwd, env, delai)

        p = paire(
            branches=[
                {"travail": "main", "miroir": "main", "creer": False},
                {"travail": "feat", "miroir": "feat", "creer": False},
                {"travail": "neuve", "miroir": "main", "creer": True},
            ]
        )
        etats = [r["etat"] for r in self.f.passe_paire(p, enregistrer)]
        self.assertEqual(etats, ["avance", "divergent", "creee"])
        self.assertEqual(instantane(self.f.miroir), avant)
        pushes = [(a, cwd) for a, cwd in appels if a[0] == "push"]
        self.assertEqual(len(pushes), 2)
        for args, cwd in pushes:
            self.assertEqual(cwd, self.f.miroir)
            for interdit in (
                "--force",
                "-f",
                "--force-with-lease",
                "--mirror",
            ):
                self.assertNotIn(interdit, args)
            self.assertFalse(any(a.startswith("+") for a in args))
            self.assertFalse(any(a.startswith("--force") for a in args))
        self.assertFalse(any(cwd == self.f.travail for a, cwd in pushes))


class TestLaLigneDeCommande(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.f = Forge(dossier.name)
        a = self.f.commit(message="a")
        b = self.f.commit(a, "b")
        c = self.f.commit(a, "c")
        self.f.poser(self.f.miroir, "main", b)
        self.f.poser(self.f.travail, "main", c)
        racine = Path(dossier.name)
        (racine / "etc").mkdir()
        (racine / "etat").mkdir()
        (racine / "cred").mkdir()
        (racine / "cred" / "token").write_text(JETON + "\n")
        (racine / "etc" / "token").write_text(JETON)
        self.env_fichier = racine / "etc" / "environment"
        self.env_fichier.write_text(
            "FORGE_SYNC_URL=http://127.0.0.1:3000\n"
            f"FORGE_SYNC_REPOS={self.f.depots}\n"
            "FORGE_SYNC_ACCOUNT=compte\n"
        )
        self.config = racine / "etc" / "config.json"
        self.etat = racine / "etat" / "etat.json"
        self.verrou = racine / "etat" / "verrou"
        for nom, valeur in (
            ("CONFIG", str(self.config)),
            ("JETON", str(racine / "etc" / "token")),
            ("ENVIRONNEMENT", str(self.env_fichier)),
            ("ETAT", str(self.etat)),
            ("VERROU", str(self.verrou)),
        ):
            p = mock.patch.object(fs, nom, valeur)
            p.start()
            self.addCleanup(p.stop)
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("FORGE_SYNC_")
        }
        env["CREDENTIALS_DIRECTORY"] = str(racine / "cred")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(fs.os, "geteuid", return_value=1000)
        p.start()
        self.addCleanup(p.stop)

    def ecrire_config(self, paires):
        self.config.write_text(json.dumps({"version": 1, "paires": paires}))

    def main(self, argv, entree=None):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = fs.main(argv, entree)
        return code, sortie.getvalue()

    def test_une_divergence_rend_0_une_erreur_1(self):
        self.ecrire_config([paire()])
        code, sortie = self.main(["passe"])
        self.assertEqual(code, 0)
        self.assertIn("org/r main: divergent", sortie)
        etat = json.loads(self.etat.read_text())
        self.assertEqual(etat["resultats"][0]["etat"], "divergent")
        self.assertEqual(self.etat.stat().st_mode & 0o777, 0o644)
        self.ecrire_config([paire("org/r", "org-mirror/zz")])
        self.assertEqual(self.main(["passe"])[0], 1)
        self.assertNotIn(JETON, self.etat.read_text())

    def test_root_est_refuse(self):
        self.ecrire_config([paire()])
        with mock.patch.object(fs.os, "geteuid", return_value=0):
            self.assertEqual(self.main(["passe"])[0], 2)
        self.assertFalse(self.etat.exists())

    def test_un_verrou_tenu_ne_lance_rien(self):
        self.ecrire_config([paire()])
        with open(self.verrou, "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            code, sortie = self.main(["passe"])
        self.assertEqual(code, 0)
        self.assertIn("already running", sortie)
        self.assertFalse(self.etat.exists())

    def test_sans_jeton_ou_sans_configuration(self):
        self.assertEqual(self.main(["passe"])[0], 2)
        self.ecrire_config([paire()])
        os.environ.pop("CREDENTIALS_DIRECTORY")
        self.assertEqual(self.main(["passe"])[0], 2)

    def test_configurer_fusionne(self):
        self.ecrire_config([paire("org/a", "org-mirror/a")])
        neuve = {
            "version": 1,
            "paires": [paire(), paire("ORG/A", "org-mirror/a")],
        }
        code, sortie = self.main(
            ["configurer"], io.StringIO(json.dumps(neuve))
        )
        self.assertEqual(code, 0)
        self.assertIn("2 pairs (1 new)", sortie)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o644)
        config = json.loads(self.config.read_text())
        self.assertEqual(
            [p["depot"] for p in config["paires"]], ["ORG/A", "org/r"]
        )

    def test_configurer_refuse_une_entree_invalide(self):
        self.ecrire_config([paire()])
        avant = self.config.read_bytes()
        for entree in (
            "{",
            json.dumps({"version": 1, "paires": [paire("a/r", "b/r")]}),
        ):
            with self.subTest(entree=entree):
                self.assertEqual(
                    self.main(["configurer"], io.StringIO(entree))[0], 2
                )
                self.assertEqual(self.config.read_bytes(), avant)

    def test_retirer(self):
        self.ecrire_config([paire(), paire("org/a", "org-mirror/a")])
        self.assertEqual(self.main(["retirer", "ORG/R"])[0], 0)
        config = json.loads(self.config.read_text())
        self.assertEqual([p["depot"] for p in config["paires"]], ["org/a"])

    def test_retirer_sans_configuration_reussit(self):
        code, sortie = self.main(["retirer", "org/r"])
        self.assertEqual(code, 0)
        self.assertIn("nothing to remove", sortie)
        self.assertFalse(self.config.exists())

    def test_etat_sans_jeton(self):
        self.ecrire_config([paire()])
        self.main(["passe"])
        code, sortie = self.main(["etat"])
        self.assertEqual(code, 0)
        etat = json.loads(sortie)
        self.assertTrue(etat["jeton"])
        self.assertEqual(etat["compte"], "compte")
        self.assertEqual(etat["erreurs_config"], [])
        self.assertEqual(etat["etat"]["resultats"][0]["etat"], "divergent")
        self.assertNotIn(JETON, sortie)
        self.assertNotIn(
            base64.b64encode(f"compte:{JETON}".encode()).decode(), sortie
        )


if __name__ == "__main__":
    unittest.main()
