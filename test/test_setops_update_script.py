#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le script qui rapatrie le moteur Set-OPS, éprouvé par ce qu'il FAIT.

Il tourne pour de bon, dans un dossier temporaire qui imite la racine :
copie du script, de la fusion et des manifestes, `env_var.sh` minimal,
`.venv.erplibre/bin/python` qui relance le vrai interpréteur. `repo` et
`git` sont faux et consignent leurs appels — le faux git répond aussi à
« git version », que GitPython lance à son import. `pkill` est faux et
consigné, pour qu'aucun démon réel du poste ne soit visé. La fusion, elle,
est la vraie.

Le script lance le démon en arrière-plan, et son trap EXIT le tue : un
faux démon tué avant d'avoir écrit sa ligne ferait passer pour « aucun
démon lancé » une garde placée APRÈS lui. Le script tourne donc avec
SIGTERM ignoré, disposition que le faux démon hérite : il va au bout, et
`capture_output` attend sa fin, puisqu'il tient les mêmes tubes. Seule
l'épreuve du trap lui-même tourne sans, avec un faux démon qui dure.

Le manifeste copié pose le moteur à un chemin inventé : un chemin recopié
dans le script, plutôt que lu dans le manifeste, ne le suit pas.

Les propriétés :
- les gardes passent AVANT tout effet de bord, et toutes parlent dans la
  même exécution : un refus ne lance ni démon git, ni fusion, ni `repo` ;
- un dossier que repo n'a pas posé est refusé intact, avec la commande qui
  le met de côté ;
- un démon resté d'avant est arrêté avant le lancement, par un motif qui
  vise ce que le script lance ; le démon lancé ne survit pas au script ;
- le sync ne vise que le moteur, et borne ce qu'il rapatrie à la branche
  d'amont (-c) ; le verdict est celui de la fusion, de `repo init` ou de
  `repo sync`, le premier qui échoue. Le contrôle positif — chemin libre,
  tout passe — prouve que les gardes savent laisser passer.
"""

import itertools
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import xml.etree.ElementTree as ET

from script.setops import engine

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT = os.path.join("script", "manifest", "update_manifest_local_setops.sh")
BRANCHE = "branche-inventee"
BRANCHE_CONTENANTE = "branche-contenante-inventee"
CHEMIN_RAPATRIE = "private/repo/Moteur-Rapatrie-Invente"
# Les codes de refus que documentent l'en-tête du script et doc/SETOPS.
CODES_DE_REFUS = (1, engine.RC_DECLARATION, engine.RC_OCCUPE)

# « symbolic-ref » échoue sur FAUX_SYMREF_RC non nul, comme sur un HEAD
# détaché. « branch » répond alors comme un vrai git : d'abord la
# pseudo-ligne entre parenthèses qui nomme le HEAD détaché, puis
# FAUX_BRANCHE_CONTENANTE si une branche contient ce HEAD.
FAUX_GIT = f"""#!/bin/sh
echo "$*" >> "$APPELS_GIT"
case "$1" in
  symbolic-ref)
    [ "${{FAUX_SYMREF_RC:-0}}" = 0 ] || exit "$FAUX_SYMREF_RC"
    echo "{BRANCHE}" ;;
  branch)
    echo "(HEAD detached at 0123abc)"
    [ -z "$FAUX_BRANCHE_CONTENANTE" ] || echo "$FAUX_BRANCHE_CONTENANTE" ;;
  version) echo "git version 2.40.0" ;;
esac
exit 0
"""

FAUX_REPO = """#!/bin/sh
echo "$*" >> "$APPELS_REPO"
case "$1" in
  init) exit "${FAUX_INIT_RC:-0}" ;;
  sync) exit "${FAUX_SYNC_RC:-0}" ;;
esac
exit 0
"""


def executable(chemin, texte):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(texte)
    os.chmod(chemin, os.stat(chemin).st_mode | stat.S_IXUSR)


def poser_le_moteur_en(racine, chemin):
    """Réécrit le manifeste du moteur copié sous `racine` pour qu'il le pose
    en `chemin`."""
    fichier = os.path.join(racine, engine.MANIFEST)
    arbre = ET.parse(fichier)
    (projet,) = [
        p
        for p in arbre.getroot().findall("project")
        if engine.GROUP in engine.groups_of(p.get("groups"))
    ]
    projet.set("path", chemin)
    arbre.write(fichier, encoding="unicode")


class RacineImitee(unittest.TestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine, True)
        for relatif in (
            SCRIPT,
            os.path.join("script", "git", "git_merge_repo_manifest.py"),
            engine.MANIFEST,
            os.path.join("manifest", "git_manifest_erplibre.xml"),
            os.path.join("conf", "git_manifest.csv"),
            os.path.join("conf", "git_manifest_setops.csv"),
        ):
            cible = os.path.join(self.racine, relatif)
            os.makedirs(os.path.dirname(cible), exist_ok=True)
            shutil.copy2(os.path.join(RACINE, relatif), cible)
        poser_le_moteur_en(self.racine, CHEMIN_RAPATRIE)
        self.decl = engine.declaration(self.racine)
        # Contrôle : une racine qui retomberait sur le vrai manifeste ne
        # distinguerait plus un chemin recopié.
        self.assertEqual(CHEMIN_RAPATRIE, self.decl.path)
        self.assertNotEqual(engine.declaration(RACINE).path, self.decl.path)
        with open(os.path.join(self.racine, "env_var.sh"), "w") as f:
            f.write('EL_MANIFEST_DEV="./manifest/git_manifest_erplibre.xml"\n')
        executable(
            os.path.join(self.racine, ".venv.erplibre", "bin", "python"),
            f'#!/bin/sh\nexec "{sys.executable}" "$@"\n',
        )
        faux = os.path.join(self.racine, "faux-bin")
        executable(os.path.join(faux, "git"), FAUX_GIT)
        executable(
            os.path.join(faux, "pkill"),
            '#!/bin/sh\necho "pkill $*" >> "$APPELS_GIT"\nexit 1\n',
        )
        self.appels_git = os.path.join(self.racine, "appels.git")
        self.appels_repo = os.path.join(self.racine, "appels.repo")
        self.env = dict(
            os.environ,
            PATH=faux + os.pathsep + os.environ.get("PATH", ""),
            PYTHONPATH=RACINE,
            APPELS_GIT=self.appels_git,
            APPELS_REPO=self.appels_repo,
            EL_VERBOSE="0",
        )

    def poser_repo(self):
        executable(
            os.path.join(self.racine, ".venv.erplibre", "bin", "repo"),
            FAUX_REPO,
        )

    def clone_manuel(self, git_init=False):
        dossier = os.path.join(self.racine, self.decl.path)
        os.makedirs(dossier)
        self.travail = os.path.join(dossier, "travail-en-cours")
        with open(self.travail, "w") as f:
            f.write("x")
        if git_init:
            subprocess.run(["git", "init", "-q", dossier], check=True)

    def lister(self, *chemins):
        """Écrit `.repo/project.list`, comme après un sync qui visait
        `chemins`."""
        os.makedirs(os.path.join(self.racine, ".repo"), exist_ok=True)
        with open(
            os.path.join(self.racine, ".repo", "project.list"), "w"
        ) as f:
            f.write("".join(c + "\n" for c in chemins))

    def arbre_de_repo(self):
        """Le moteur tel que Google Repo le pose : listé, son `.git` lien
        vers `.repo/projects/`."""
        arbre = os.path.join(self.racine, self.decl.path)
        depot = os.path.join(
            self.racine, ".repo", "projects", self.decl.path + ".git"
        )
        os.makedirs(arbre)
        os.makedirs(depot)
        os.symlink(os.path.relpath(depot, arbre), os.path.join(arbre, ".git"))
        self.lister(self.decl.path)

    def lancer(self, **env):
        fait = subprocess.run(
            ["./" + SCRIPT],
            cwd=self.racine,
            env=dict(self.env, **env),
            capture_output=True,
            text=True,
            timeout=120,
            preexec_fn=lambda: signal.signal(signal.SIGTERM, signal.SIG_IGN),
        )
        return fait.returncode, fait.stdout + fait.stderr

    @staticmethod
    def lignes(chemin):
        if not os.path.exists(chemin):
            return []
        with open(chemin) as f:
            return [ligne.split() for ligne in f.read().splitlines()]

    def demons(self):
        return [a for a in self.lignes(self.appels_git) if a[:1] == ["daemon"]]

    def effets_du_demon(self):
        """Le démon lancé, ou l'arrêt d'un démon resté d'avant."""
        return [
            a
            for a in self.lignes(self.appels_git)
            if a[:1] in (["daemon"], ["pkill"])
        ]

    def fusionne(self):
        return os.path.exists(
            os.path.join(
                self.racine,
                ".repo",
                "local_manifests",
                "erplibre_manifest.xml",
            )
        )


class TestLesGardesPassentAvantToutEffet(RacineImitee):
    def test_without_repo_it_names_the_installer_and_touches_nothing(self):
        rc, sortie = self.lancer()
        self.assertIn(rc, CODES_DE_REFUS, sortie)
        self.assertIn("./script/install/install_git_repo.sh", sortie)
        self.assertEqual([], self.effets_du_demon())
        self.assertFalse(self.fusionne())

    def test_a_repo_that_cannot_run_is_refused_like_a_missing_one(self):
        # Présent sans droit d'exécution, repo échouerait APRÈS le démon et
        # la fusion : la garde le refuse avant, comme s'il manquait.
        self.poser_repo()
        os.chmod(
            os.path.join(self.racine, ".venv.erplibre", "bin", "repo"), 0o644
        )
        rc, sortie = self.lancer()
        self.assertEqual(1, rc, sortie)
        self.assertIn("./script/install/install_git_repo.sh", sortie)
        self.assertEqual([], self.lignes(self.appels_repo))
        self.assertEqual([], self.effets_du_demon())
        self.assertFalse(self.fusionne())

    def test_without_its_interpreter_it_refuses_with_a_documented_code(self):
        # La garde de l'emplacement tourne dans .venv.erplibre : sans son
        # interpréteur exécutable, le refus rend 1, dit que l'emplacement
        # n'a pas pu être vérifié, et rien ne bouge — clone manuel présent
        # ou non. Avec repo posé, seule cette garde peut poser le code ; et
        # bash, qui nomme lui aussi le chemin dans son erreur brute, ne dit
        # pas cette phrase.
        for panne, avec_repo, clone in itertools.product(
            ("absent", "non exécutable"), (False, True), (False, True)
        ):
            with self.subTest(interprete=panne, repo=avec_repo, clone=clone):
                self.setUp()  # une racine neuve par cas
                python = os.path.join(
                    self.racine, ".venv.erplibre", "bin", "python"
                )
                if panne == "absent":
                    os.remove(python)
                else:
                    os.chmod(python, 0o644)
                if avec_repo:
                    self.poser_repo()
                if clone:
                    self.clone_manuel()
                rc, sortie = self.lancer()
                self.assertEqual(1, rc, sortie)
                self.assertIn("n'a pas pu être vérifié", sortie)
                self.assertEqual([], self.lignes(self.appels_repo))
                self.assertEqual([], self.effets_du_demon())
                self.assertFalse(
                    os.path.exists(os.path.join(self.racine, ".repo"))
                )
                if clone:
                    self.assertTrue(os.path.isfile(self.travail))

    def refus_intact(self, sortie):
        """Le dossier occupant est nommé avec sa mise de côté, et rien n'a
        bougé : ni repo, ni démon, ni fusion, ni le travail en cours."""
        self.assertIn(engine.mise_de_cote(self.decl.path), sortie)
        self.assertEqual([], self.lignes(self.appels_repo))
        self.assertEqual([], self.effets_du_demon())
        self.assertFalse(self.fusionne())
        self.assertTrue(os.path.isfile(self.travail))

    def test_a_manual_clone_is_refused_untouched(self):
        self.poser_repo()
        self.clone_manuel()
        rc, sortie = self.lancer()
        self.assertEqual(engine.RC_OCCUPE, rc, sortie)
        self.refus_intact(sortie)

    def test_a_manual_clone_beside_a_real_repo_is_refused_untouched(self):
        # Le cas ordinaire : un poste déjà initialisé par repo, dont la
        # liste ne nomme pas le moteur.
        self.poser_repo()
        self.lister("addons/Autre_Invente")
        self.clone_manuel()
        rc, sortie = self.lancer()
        self.assertEqual(engine.RC_OCCUPE, rc, sortie)
        self.refus_intact(sortie)

    def test_a_manual_clone_at_a_listed_path_is_refused_untouched(self):
        # Un sync en échec liste le chemin sans rien y poser : le clone
        # manuel qui s'y trouve ensuite n'est pas pour autant à repo.
        self.poser_repo()
        self.lister(self.decl.path)
        self.clone_manuel(git_init=True)
        rc, sortie = self.lancer()
        self.assertEqual(engine.RC_OCCUPE, rc, sortie)
        self.refus_intact(sortie)

    def test_a_detached_head_without_branch_is_refused_before_any_effect(
        self,
    ):
        self.poser_repo()
        rc, sortie = self.lancer(FAUX_SYMREF_RC="1")
        self.assertIn(rc, CODES_DE_REFUS, sortie)
        self.assertIn("branche", sortie)
        self.assertEqual([], self.lignes(self.appels_repo))
        self.assertEqual([], self.effets_du_demon())
        self.assertFalse(self.fusionne())

    def test_every_refusal_speaks_in_the_same_run(self):
        # Régler un refus ne fait pas découvrir le suivant au lancement
        # d'après. Le code du module l'emporte : 3 pour le chemin occupé.
        self.clone_manuel()
        rc, sortie = self.lancer(FAUX_SYMREF_RC="1")
        self.assertEqual(engine.RC_OCCUPE, rc, sortie)
        self.assertIn("./script/install/install_git_repo.sh", sortie)
        self.assertIn("branche", sortie)
        self.refus_intact(sortie)


class TestLeRapatriement(RacineImitee):
    def sync_vise(self, appel):
        """Les arguments positionnels d'un « repo sync » : les projets."""
        projets, sauter = [], False
        for mot in appel[1:]:
            if sauter:
                sauter = False
            elif mot in ("-j", "-m"):
                sauter = True
            elif not mot.startswith("-"):
                projets.append(mot)
        return projets

    def test_a_free_path_inits_on_a_branch_then_syncs_the_engine_alone(self):
        self.poser_repo()
        rc, sortie = self.lancer()
        self.assertEqual(0, rc, sortie)
        appels = self.lignes(self.appels_repo)
        self.assertEqual(["init", "sync"], [a[0] for a in appels], appels)
        init, sync = appels
        # Une branche, jamais un SHA nu : « repo init -b <sha> » échoue sur
        # un espace de travail neuf.
        self.assertEqual(BRANCHE, init[init.index("-b") + 1])
        self.assertEqual([self.decl.path], self.sync_vise(sync))
        # Le sync borne ce qu'il rapatrie à la branche d'amont, celle que
        # nomme « upstream ».
        self.assertTrue({"-c", "--current-branch"} & set(sync[1:]), sync)
        # La fusion a bien tourné, et avec le moteur.
        self.assertTrue(self.fusionne())
        local = ET.parse(
            os.path.join(
                self.racine,
                ".repo",
                "local_manifests",
                "erplibre_manifest.xml",
            )
        ).getroot()
        self.assertIn(
            self.decl.path, [p.get("path") for p in local.findall("project")]
        )
        # Le démon ne sert que la boucle locale.
        (demon,) = self.demons()
        self.assertIn("--listen=127.0.0.1", demon)

    def test_a_detached_head_takes_the_branch_that_contains_it(self):
        # git nomme d'abord le HEAD détaché, entre parenthèses : « repo
        # init » reçoit la branche qui le contient, jamais cette ligne-là.
        self.poser_repo()
        rc, sortie = self.lancer(
            FAUX_SYMREF_RC="1", FAUX_BRANCHE_CONTENANTE=BRANCHE_CONTENANTE
        )
        self.assertEqual(0, rc, sortie)
        appels = self.lignes(self.appels_repo)
        self.assertEqual(["init", "sync"], [a[0] for a in appels], appels)
        init = appels[0]
        self.assertEqual(BRANCHE_CONTENANTE, init[init.index("-b") + 1])

    def test_a_folder_repo_already_manages_is_synced_again(self):
        self.poser_repo()
        self.arbre_de_repo()
        rc, sortie = self.lancer()
        self.assertEqual(0, rc, sortie)
        self.assertEqual(
            ["init", "sync"], [a[0] for a in self.lignes(self.appels_repo)]
        )

    def test_the_sync_verdict_is_the_script_verdict(self):
        self.poser_repo()
        rc, sortie = self.lancer(FAUX_SYNC_RC="7")
        self.assertEqual(7, rc, sortie)

    def test_a_failed_init_stops_before_the_sync(self):
        self.poser_repo()
        rc, _sortie = self.lancer(FAUX_INIT_RC="5")
        self.assertEqual(5, rc)
        self.assertEqual(
            ["init"], [a[0] for a in self.lignes(self.appels_repo)]
        )

    def test_a_leftover_daemon_is_stopped_before_the_new_one_starts(self):
        # Un démon resté d'avant garde le port : le nouveau ne s'y lie pas,
        # et « repo init » lirait ce que sert l'ancien. L'arrêt vise, en
        # ligne de commande complète, le processus que le script lance —
        # sous son nom exécuté « git-daemon » — et vient AVANT ce lancement.
        self.poser_repo()
        rc, sortie = self.lancer()
        self.assertEqual(0, rc, sortie)
        effets = self.effets_du_demon()
        self.assertEqual(["pkill", "daemon"], [a[0] for a in effets], effets)
        arret, demon = effets
        self.assertIn("-f", arret)
        motif = " ".join(arret[arret.index("-f") + 1 :])
        self.assertRegex("git-" + " ".join(demon), motif)


# Le faux démon DURE : il se remplace par un « sleep » qui porte une marque
# unique, sous le PID que le script a noté. Ses descripteurs sont fermés,
# pour que `capture_output` n'attende pas sa fin.
FAUX_GIT_DEMON_DURABLE = f"""#!/usr/bin/env bash
echo "$*" >> "$APPELS_GIT"
case "$1" in
  symbolic-ref) echo "{BRANCHE}" ;;
  version) echo "git version 2.40.0" ;;
  daemon) exec -a "$MARQUE_DEMON" sleep 60 </dev/null >/dev/null 2>&1 ;;
esac
exit 0
"""

# « repo init » note si le démon vivait pendant l'exécution : le contrôle
# positif de l'épreuve du trap.
FAUX_REPO_TEMOIN = """#!/bin/sh
echo "$*" >> "$APPELS_REPO"
case "$1" in
  init)
    pgrep -f "$MARQUE_DEMON" >> "$DEMON_PENDANT_INIT"
    exit "${FAUX_INIT_RC:-0}" ;;
esac
exit 0
"""


@unittest.skipUnless(
    shutil.which("pgrep") and shutil.which("pkill"), "pgrep et pkill requis"
)
class TestLeDemonSArreteAvecLeScript(RacineImitee):
    """Le démon lancé sert tout dépôt git de la racine sur la boucle locale :
    il ne survit pas au script, qu'il réussisse ou échoue après l'avoir
    lancé. Ici SIGTERM n'est PAS ignoré : le trap doit pouvoir tuer."""

    def setUp(self):
        super().setUp()
        self.marque = "faux-demon-" + uuid.uuid4().hex
        self.addCleanup(
            subprocess.run, [shutil.which("pkill"), "-f", self.marque]
        )
        executable(
            os.path.join(self.racine, "faux-bin", "git"),
            FAUX_GIT_DEMON_DURABLE,
        )
        executable(
            os.path.join(self.racine, ".venv.erplibre", "bin", "repo"),
            FAUX_REPO_TEMOIN,
        )
        self.temoin = os.path.join(self.racine, "demon-pendant-init")

    def survivants(self):
        """Les PID qui portent la marque, après au plus deux secondes."""
        for _ in range(20):
            vivants = subprocess.run(
                [shutil.which("pgrep"), "-f", self.marque],
                capture_output=True,
                text=True,
            ).stdout.split()
            if not vivants:
                return []
            time.sleep(0.1)
        return vivants

    def test_the_daemon_it_starts_never_outlives_it(self):
        for nom, env, attendu in (
            ("succès", {}, 0),
            ("init en échec", {"FAUX_INIT_RC": "5"}, 5),
        ):
            with self.subTest(chemin=nom):
                if os.path.exists(self.temoin):
                    os.remove(self.temoin)
                fait = subprocess.run(
                    ["./" + SCRIPT],
                    cwd=self.racine,
                    env=dict(
                        self.env,
                        MARQUE_DEMON=self.marque,
                        DEMON_PENDANT_INIT=self.temoin,
                        **env,
                    ),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                self.assertEqual(attendu, fait.returncode, fait.stderr)
                # Contrôle positif : le démon vivait bien pendant le script.
                with open(self.temoin) as f:
                    self.assertTrue(f.read().split())
                self.assertEqual([], self.survivants())


if __name__ == "__main__":
    unittest.main()
