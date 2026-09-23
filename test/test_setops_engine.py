#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le moteur Set-OPS déclaré, et ce que git dit de son clone.

Tout se joue dans des dossiers temporaires : un manifeste INVENTÉ, de vrais
dépôts git dont les commits sont créés par l'épreuve, un faux `.repo/`. Le
vrai moteur n'est jamais lu — il est absent en CI, `private/repo/` étant
ignoré par git.

Les noms de forge, de dépôt et de chemin sont inventés et n'existent nulle
part ailleurs dans le dépôt.
"""

import contextlib
import hashlib
import inspect
import io
import itertools
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from script.setops import engine

FORGE = "https://forge.exemple.invalid/Orga-Inventee/"
CHEMIN = "private/repo/Moteur-Invente"
SHA_INVENTE = "0123456789abcdef0123456789abcdef01234567"


def manifeste(projets, remote="remote-inventee"):
    """Un manifeste Google Repo au texte complet, projets fournis."""
    return (
        '<?xml version="1.0" encoding="UTF-8" ?>\n<manifest>\n'
        f'  <remote name="{remote}" fetch="{FORGE}" />\n'
        f"{projets}</manifest>\n"
    )


def projet(
    chemin=CHEMIN,
    revision=SHA_INVENTE,
    groups="setops",
    remote="remote-inventee",
    upstream="main",
):
    attrs = [
        'name="Depot-Invente.git"',
        f'path="{chemin}"',
        f'remote="{remote}"',
    ]
    if revision is not None:
        attrs.append(f'revision="{revision}"')
    if upstream is not None:
        attrs.append(f'upstream="{upstream}"')
    if groups is not None:
        attrs.append(f'groups="{groups}"')
    return "  <project " + " ".join(attrs) + " />\n"


def git(dossier, *args):
    """Un appel git d'ÉPREUVE, identité fixée, qui lève s'il échoue."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_AUTHOR_NAME="Epreuve",
        GIT_AUTHOR_EMAIL="epreuve@exemple.invalid",
        GIT_COMMITTER_NAME="Epreuve",
        GIT_COMMITTER_EMAIL="epreuve@exemple.invalid",
    )
    return subprocess.run(
        ["git", "-C", dossier, *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


def nomme_la_mise_de_cote(texte, chemin):
    """Une ligne de `texte`, relue comme un shell la lirait, est-elle la
    commande qui déplace `chemin` vers `chemin.manuel` ?"""
    for ligne in texte.splitlines():
        try:
            mots = shlex.split(ligne)
        except ValueError:
            continue
        if mots == ["mv", chemin, chemin + ".manuel"]:
            return True
    return False


def annonce_l_ecrasement(texte):
    """`texte` dit-il que repo écrirait par-dessus ce qui occupe le chemin,
    sous l'une ou l'autre des deux tournures françaises du danger ?

    Seules les formes AFFIRMATIVES comptent : « par-dessus », ou le
    conditionnel « écraserai(en)t ». Le participe « écrasé » et l'infinitif
    « écraser » ne comptent pas, car ils portent les négations qui
    rassurent — « Rien n'est écrasé », « sans rien écraser »."""
    return re.search(r"par-dessus|écraserai", texte) is not None


def depot(dossier):
    """Un vrai dépôt git, un premier commit ; rend le SHA de HEAD."""
    os.makedirs(dossier, exist_ok=True)
    git(dossier, "init", "-q", "-b", "principale")
    return commit(dossier, "a")


def commit(dossier, nom):
    with open(os.path.join(dossier, nom), "w", encoding="utf-8") as f:
        f.write(nom)
    git(dossier, "add", nom)
    git(dossier, "commit", "-q", "-m", nom)
    return git(dossier, "rev-parse", "HEAD")


class TestParseManifest(unittest.TestCase):
    def test_the_declared_project_is_read_whole(self):
        decl = engine.parse_manifest(manifeste(projet()))
        self.assertEqual(CHEMIN, decl.path)
        self.assertEqual(SHA_INVENTE, decl.revision)
        self.assertEqual("main", decl.upstream)
        self.assertEqual("remote-inventee", decl.remote)

    def test_the_project_is_found_by_its_group_among_others(self):
        # Le groupe désigne le moteur, pas la position dans le fichier.
        autres = projet(chemin="ailleurs/autre", groups="mobile")
        texte = manifeste(autres + projet(groups="odoo,setops"))
        self.assertEqual(CHEMIN, engine.parse_manifest(texte).path)

    def test_no_project_in_the_group_declares_nothing(self):
        self.assertIsNone(
            engine.parse_manifest(manifeste(projet(groups="mobile")))
        )

    def test_two_projects_in_the_group_are_ambiguous(self):
        # Deux moteurs déclarés : aucun des deux n'est « le » moteur.
        texte = manifeste(projet() + projet(chemin="private/repo/Autre"))
        self.assertIsNone(engine.parse_manifest(texte))

    def test_a_truncated_manifest_declares_nothing(self):
        self.assertIsNone(engine.parse_manifest(manifeste(projet())[:-30]))
        self.assertIsNone(engine.parse_manifest(""))
        self.assertIsNone(engine.parse_manifest(None))

    def test_a_path_leaving_the_workspace_declares_nothing(self):
        # Le chemin finit dans une commande « mv » affichée : il reste sous
        # la racine, ou il n'est pas déclaré — quelle que soit l'écriture
        # qui le ramène à la racine ou au-dessus.
        for chemin in (
            "/tmp/Moteur-Invente",
            "../Moteur-Invente",
            "",
            ".",
            "./",
            "private/..",
            "..",
            "private/../..",
        ):
            with self.subTest(chemin=chemin):
                texte = manifeste(projet(chemin=chemin))
                self.assertIsNone(engine.parse_manifest(texte))

    def test_a_missing_revision_is_declared_but_not_pinned(self):
        decl = engine.parse_manifest(manifeste(projet(revision=None)))
        self.assertEqual(CHEMIN, decl.path)
        self.assertFalse(engine.is_pinned(decl.revision))

    def test_the_default_remote_stands_in_for_a_missing_one(self):
        texte = manifeste(
            '  <default remote="remote-inventee" />\n'
            + projet().replace('remote="remote-inventee" ', "")
        )
        self.assertEqual(
            "remote-inventee", engine.parse_manifest(texte).remote
        )


# Les formes de liste que Google Repo découpe en « setops » et autre chose.
FORMES_DE_GROUPES = (
    "setops",
    "odoo,setops",
    "odoo, setops",
    "odoo setops",
    "odoo,\n  setops",
)
# Des noms qui CONTIENNENT « setops » sans l'être.
FAUX_GROUPES = ("setopsx", "odoo,mysetops")


class TestGroupsOf(unittest.TestCase):
    def test_every_list_form_repo_accepts_names_the_group(self):
        for forme in FORMES_DE_GROUPES:
            with self.subTest(forme=forme):
                self.assertIn(engine.GROUP, engine.groups_of(forme))
                texte = manifeste(projet(groups=forme))
                self.assertEqual(CHEMIN, engine.parse_manifest(texte).path)

    def test_a_name_that_merely_contains_it_is_another_group(self):
        for forme in FAUX_GROUPES:
            with self.subTest(forme=forme):
                self.assertNotIn(engine.GROUP, engine.groups_of(forme))
                texte = manifeste(projet(groups=forme))
                self.assertIsNone(engine.parse_manifest(texte))

    def test_no_attribute_is_no_group(self):
        self.assertEqual([], engine.groups_of(None))
        self.assertEqual([], engine.groups_of(" , "))


class TestMiseDeCote(unittest.TestCase):
    def test_the_command_reads_back_as_one_path_per_argument(self):
        # parse_manifest ne restreint pas les caractères du chemin : la
        # commande affichée se recopie telle quelle dans un shell.
        for chemin in (
            CHEMIN,
            "private/repo/Moteur d'Essai Fictif",
            'private/repo/Moteur "$Invente"',
        ):
            with self.subTest(chemin=chemin):
                self.assertEqual(
                    ["mv", chemin, chemin + ".manuel"],
                    shlex.split(engine.mise_de_cote(chemin)),
                )


class TestLeDangerSeLitAffirme(unittest.TestCase):
    """Le juge de l'écrasement lit le danger AFFIRMÉ : une phrase qui
    rassure emploie les mêmes mots, et nie ce qu'il faut dire."""

    def test_only_the_affirmed_danger_is_read(self):
        for texte, attendu in (
            ("extrairait sa révision par-dessus les fichiers présents", True),
            ("repo sync écraserait les fichiers présents", True),
            ("repo sync écraseraient ce qui occupe le chemin", True),
            ("Rien n'est écrasé ici", False),
            ("sans jamais rien écraser", False),
            ("refuserait d'y poser le moteur", False),
        ):
            with self.subTest(texte=texte):
                self.assertIs(attendu, annonce_l_ecrasement(texte))


class TestIsPinned(unittest.TestCase):
    def test_a_full_sha_is_pinned(self):
        self.assertTrue(engine.is_pinned(SHA_INVENTE))

    def test_anything_that_moves_is_not(self):
        for revision in (
            "main",
            "refs/tags/v1.0",
            SHA_INVENTE[:-1],
            SHA_INVENTE + "8",
            "g" + SHA_INVENTE[1:],
            "-" + SHA_INVENTE[1:],
            "",
            None,
        ):
            with self.subTest(revision=revision):
                self.assertFalse(engine.is_pinned(revision))


class TestDeclaration(unittest.TestCase):
    def test_it_reads_the_dedicated_manifest_under_the_root(self):
        with tempfile.TemporaryDirectory() as racine:
            os.makedirs(os.path.join(racine, "manifest"))
            chemin = os.path.join(racine, engine.MANIFEST)
            with open(chemin, "w", encoding="utf-8") as f:
                f.write(manifeste(projet()))
            self.assertEqual(CHEMIN, engine.declaration(racine).path)

    def test_no_manifest_is_no_declaration_not_an_error(self):
        with tempfile.TemporaryDirectory() as racine:
            self.assertIsNone(engine.declaration(racine))


class TestManagedByRepo(unittest.TestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", self.racine])

    def liste(self, *chemins):
        os.makedirs(os.path.join(self.racine, ".repo"), exist_ok=True)
        with open(
            os.path.join(self.racine, ".repo", "project.list"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write("".join(c + "\n" for c in chemins))

    def test_without_repo_nothing_can_be_said(self):
        self.assertIsNone(engine.managed_by_repo(self.racine, CHEMIN))

    def test_a_listed_path_is_managed(self):
        self.liste("addons/Autre", CHEMIN)
        self.assertIs(True, engine.managed_by_repo(self.racine, CHEMIN))

    def test_an_unlisted_path_is_not(self):
        self.liste("addons/Autre")
        self.assertIs(False, engine.managed_by_repo(self.racine, CHEMIN))

    def test_a_path_is_compared_normalised(self):
        self.liste(CHEMIN)
        self.assertIs(True, engine.managed_by_repo(self.racine, CHEMIN + "/"))

    def test_an_initialised_but_never_synced_repo_manages_nothing(self):
        os.makedirs(os.path.join(self.racine, ".repo"))
        self.assertIs(False, engine.managed_by_repo(self.racine, CHEMIN))

    def test_an_unreadable_list_is_unknown(self):
        os.makedirs(os.path.join(self.racine, ".repo", "project.list"))
        self.assertIsNone(engine.managed_by_repo(self.racine, CHEMIN))


class TestRepoWorktree(unittest.TestCase):
    """Un arbre que Google Repo a posé se reconnaît à son `.git`, qui mène
    sous `.repo/` ; un clone manuel garde son dépôt dans l'arbre."""

    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", self.racine])
        self.arbre = os.path.join(self.racine, CHEMIN)
        os.makedirs(self.arbre)
        self.dotgit = os.path.join(self.arbre, ".git")

    def vers(self, *sous_racine):
        """Crée un dossier sous la racine ; rend son chemin vu de l'arbre."""
        cible = os.path.join(self.racine, *sous_racine)
        os.makedirs(cible, exist_ok=True)
        return os.path.relpath(cible, self.arbre)

    def verdict(self):
        return engine.repo_worktree(self.racine, CHEMIN)

    def test_a_link_into_repo_projects_is_a_repo_tree(self):
        os.symlink(
            self.vers(".repo", "projects", CHEMIN + ".git"), self.dotgit
        )
        self.assertIs(True, self.verdict())

    def test_a_gitdir_file_into_repo_is_a_repo_tree(self):
        # Forme des arbres « git worktree » que repo sait poser.
        with open(self.dotgit, "w") as f:
            f.write("gitdir: " + self.vers(".repo", "worktrees", "x") + "\n")
        self.assertIs(True, self.verdict())

    def test_a_manual_clone_keeps_its_repository_inside(self):
        os.makedirs(os.path.join(self.racine, ".repo", "projects"))
        git(self.arbre, "init", "-q")
        self.assertIs(False, self.verdict())

    def test_a_tree_without_git_is_not_one(self):
        # repo y extrairait sa révision par-dessus les fichiers présents.
        self.assertIs(False, self.verdict())

    def test_where_the_link_leads_decides_not_how_it_is_written(self):
        # Chaque cible porte « .repo » dans son texte et mène hors du
        # .repo/ de la racine.
        self.vers("ailleurs-invente")
        cibles = {
            "lien": self.vers("ailleurs", ".repo", "projects", "p.git"),
            "lien qui ressort": os.path.join(
                self.vers(".repo"), "..", "ailleurs-invente"
            ),
            # Un voisin dont le NOM commence comme .repo sans en être un
            # sous-dossier.
            "voisin au même préfixe": self.vers(
                ".repo.invente", "projects", "p.git"
            ),
        }
        for nom, cible in cibles.items():
            with self.subTest(forme=nom):
                os.symlink(cible, self.dotgit)
                try:
                    self.assertIs(False, self.verdict())
                finally:
                    os.remove(self.dotgit)
        with open(self.dotgit, "w") as f:
            f.write("gitdir: " + cibles["lien"] + "\n")
        self.assertIs(False, self.verdict())

    def test_an_unreadable_gitdir_file_is_unknown(self):
        if os.geteuid() == 0:
            self.skipTest("root lit un fichier sans droit de lecture")
        with open(self.dotgit, "w") as f:
            f.write("gitdir: " + self.vers(".repo", "worktrees", "x") + "\n")
        os.chmod(self.dotgit, 0)
        self.addCleanup(os.chmod, self.dotgit, 0o600)
        self.assertIsNone(self.verdict())


class TestRelationToPin(unittest.TestCase):
    """Égal, en avance, en retard, divergé, absente, inconnue — sans
    réseau."""

    def setUp(self):
        self.moteur = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", self.moteur])
        self.base = depot(self.moteur)

    def test_at_the_pin(self):
        self.assertEqual(
            (engine.EGAL, 0), engine.relation_to_pin(self.moteur, self.base)
        )

    def test_a_pin_written_in_capitals_is_the_same_commit(self):
        # is_pinned accepte les majuscules : la casse ne change pas la
        # relation.
        self.assertEqual(
            (engine.EGAL, 0),
            engine.relation_to_pin(self.moteur, self.base.upper()),
        )
        commit(self.moteur, "b")
        self.assertEqual(
            (engine.AVANCE, 1),
            engine.relation_to_pin(self.moteur, self.base.upper()),
        )

    def test_ahead_of_the_pin_counts_the_extra_commits(self):
        commit(self.moteur, "b")
        commit(self.moteur, "c")
        self.assertEqual(
            (engine.AVANCE, 2), engine.relation_to_pin(self.moteur, self.base)
        )

    def test_behind_the_pin_counts_the_missing_commits(self):
        commit(self.moteur, "b")
        epingle = commit(self.moteur, "c")
        git(self.moteur, "checkout", "-q", "--detach", self.base)
        self.assertEqual(
            (engine.RETARD, 2), engine.relation_to_pin(self.moteur, epingle)
        )

    def test_diverged_from_the_pin(self):
        epingle = commit(self.moteur, "b")
        git(self.moteur, "checkout", "-q", "--detach", self.base)
        commit(self.moteur, "c")
        relation, _n = engine.relation_to_pin(self.moteur, epingle)
        self.assertEqual(engine.DIVERGE, relation)

    def test_a_pin_the_clone_never_fetched_is_absent(self):
        """HEAD se lit, et l'objet épinglé n'est pas dans le clone : c'est
        un constat, que le rapatriement règle, et non une ignorance."""
        self.assertEqual(
            (engine.ABSENTE, None),
            engine.relation_to_pin(self.moteur, SHA_INVENTE),
        )

    def test_a_pin_naming_an_object_other_than_a_commit_is_unknown(self):
        # L'objet est dans le clone, donc pas absent, et un fichier n'a pas
        # de place face au HEAD.
        fichier = git(self.moteur, "rev-parse", "HEAD:a")
        self.assertEqual(
            (engine.INCONNUE, None),
            engine.relation_to_pin(self.moteur, fichier),
        )

    def test_a_pin_naming_an_annotated_tag_is_read_as_its_commit(self):
        """Un tag annoté est un objet à lui, dont le SHA n'est celui d'aucun
        commit : l'épingle se compare au commit qu'il désigne."""
        git(self.moteur, "tag", "-a", "-m", "t", "etiquette-inventee")
        tag = git(self.moteur, "rev-parse", "etiquette-inventee")
        self.assertNotEqual(self.base, tag, "le tag n'est pas annoté")
        self.assertEqual(
            (engine.EGAL, 0), engine.relation_to_pin(self.moteur, tag)
        )
        # Contrôle positif : les autres relations se lisent par le tag.
        suivant = commit(self.moteur, "b")
        self.assertEqual(
            (engine.AVANCE, 1), engine.relation_to_pin(self.moteur, tag)
        )
        git(self.moteur, "tag", "-a", "-m", "t", "suivante-inventee", suivant)
        tag_suivant = git(self.moteur, "rev-parse", "suivante-inventee")
        git(self.moteur, "checkout", "-q", "--detach", self.base)
        self.assertEqual(
            (engine.RETARD, 1),
            engine.relation_to_pin(self.moteur, tag_suivant),
        )
        commit(self.moteur, "c")
        self.assertEqual(
            (engine.DIVERGE, None),
            engine.relation_to_pin(self.moteur, tag_suivant),
        )

    def test_a_git_that_falls_silent_after_head_is_unknown_not_absent(self):
        """HEAD se lit, puis git ne répond plus — délai dépassé, processus
        tué : rien n'établit que l'épingle manque, la relation reste
        inconnue."""
        vrai_git = engine._git
        appels = []

        def repond_une_fois(dossier, *args):
            appels.append(args)
            return vrai_git(dossier, *args) if len(appels) == 1 else None

        with mock.patch.object(engine, "_git", repond_une_fois):
            relation = engine.relation_to_pin(self.moteur, SHA_INVENTE)
        self.assertEqual((engine.INCONNUE, None), relation)
        self.assertGreater(len(appels), 1, "git n'a pas été réinterrogé")

    def test_a_repository_git_cannot_read_is_unknown(self):
        # Un HEAD illisible : git ne reconnaît plus le dépôt, et ne dit
        # rien de ce qu'il contient.
        with open(os.path.join(self.moteur, ".git", "HEAD"), "w") as f:
            f.write("tete-illisible-inventee\n")
        self.assertEqual(
            (engine.INCONNUE, None),
            engine.relation_to_pin(self.moteur, SHA_INVENTE),
        )

    def test_every_relation_is_reached_by_its_own_situation(self):
        """Contrôle positif du vocabulaire clos : chaque relation se
        provoque sur un vrai dépôt, et deux situations distinctes n'en
        partagent aucune. Un terme que rien ne produit, ou deux causes
        rendues sous un même terme, rougissent ici."""
        vues = {}
        b = commit(self.moteur, "b")
        vues["à l'épingle"] = engine.relation_to_pin(self.moteur, b)[0]
        vues["en avance"] = engine.relation_to_pin(self.moteur, self.base)[0]
        git(self.moteur, "checkout", "-q", "--detach", self.base)
        vues["en retard"] = engine.relation_to_pin(self.moteur, b)[0]
        commit(self.moteur, "c")
        vues["divergé"] = engine.relation_to_pin(self.moteur, b)[0]
        vues["jamais rapatriée"] = engine.relation_to_pin(
            self.moteur, SHA_INVENTE
        )[0]
        with open(os.path.join(self.moteur, ".git", "HEAD"), "w") as f:
            f.write("tete-illisible-inventee\n")
        vues["illisible"] = engine.relation_to_pin(self.moteur, b)[0]
        self.assertEqual(set(engine.RELATIONS), set(vues.values()), vues)
        self.assertEqual(len(vues), len(set(vues.values())), vues)

    def test_a_branch_name_is_not_a_pin(self):
        # « principale » se résout dans ce dépôt : la fonction refuse quand
        # même, une branche bouge.
        self.assertEqual(
            (engine.INCONNUE, None),
            engine.relation_to_pin(self.moteur, "principale"),
        )

    def test_an_absent_engine_is_unknown(self):
        absent = os.path.join(self.moteur, "absent")
        self.assertEqual(
            (engine.INCONNUE, None), engine.relation_to_pin(absent, self.base)
        )

    def test_a_plain_folder_never_answers_for_the_repository_above(self):
        # Un dossier sans .git posé DANS un dépôt : git remonterait au
        # dépôt englobant, dont le HEAD vaut justement l'épingle.
        dedans = os.path.join(self.moteur, "copie-sans-git")
        os.makedirs(dedans)
        self.assertEqual(
            (engine.INCONNUE, None), engine.relation_to_pin(dedans, self.base)
        )


class TestDirtyCount(unittest.TestCase):
    def setUp(self):
        self.moteur = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", self.moteur])
        depot(self.moteur)

    def test_a_clean_tree_counts_zero(self):
        self.assertEqual(0, engine.dirty_count(self.moteur))

    def test_modified_and_untracked_files_both_count(self):
        with open(os.path.join(self.moteur, "a"), "w") as f:
            f.write("modifie")
        with open(os.path.join(self.moteur, "nouveau"), "w") as f:
            f.write("x")
        self.assertEqual(2, engine.dirty_count(self.moteur))

    def test_a_plain_folder_inside_a_repository_is_unknown(self):
        dedans = os.path.join(self.moteur, "copie-sans-git")
        os.makedirs(dedans)
        with open(os.path.join(self.moteur, "sale"), "w") as f:
            f.write("x")
        self.assertIsNone(engine.dirty_count(dedans))


class TestLEnvironnementGitNestPasHerite(unittest.TestCase):
    """Un `GIT_*` hérité — posé par un hook, un « rebase -x » — viserait un
    autre dépôt. Les lectures du moteur répondent comme s'il n'existait pas.
    """

    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", self.racine])
        depot(self.racine)
        self.moteur = os.path.join(self.racine, CHEMIN)
        self.epingle = depot(self.moteur)
        commit(self.moteur, "b")
        # Un dépôt qui diffère sur les trois lectures : un commit sans
        # rapport, et des règles qui ignorent tout.
        self.etranger = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", self.etranger])
        git(self.etranger, "init", "-q")
        commit(self.etranger, "etranger-seul")
        with open(
            os.path.join(self.etranger, ".git", "info", "exclude"), "w"
        ) as f:
            f.write("*\n")

    def lectures(self):
        return (
            engine.relation_to_pin(self.moteur, self.epingle),
            engine.dirty_count(self.moteur),
            engine.parent_is_ignored(self.racine, CHEMIN),
        )

    def git_brut(self):
        """Ce que git répond sans filtre, dans l'environnement courant :
        code de retour et sortie."""
        faits = [
            subprocess.run(
                ["git", "-C", self.moteur, *args],
                capture_output=True,
                text=True,
            )
            for args in (("rev-parse", "HEAD"), ("status", "--porcelain"))
        ]
        return [(fait.returncode, fait.stdout) for fait in faits]

    def test_an_inherited_git_variable_never_changes_the_answer(self):
        with mock.patch.dict(os.environ):
            for nom in [k for k in os.environ if k.startswith("GIT_")]:
                del os.environ[nom]
            reference, brut = self.lectures(), self.git_brut()
        self.assertEqual(((engine.AVANCE, 1), 0, False), reference)
        dotgit = os.path.join(self.etranger, ".git")
        for env in (
            {"GIT_DIR": dotgit},
            {"GIT_DIR": dotgit, "GIT_WORK_TREE": self.etranger},
            {"GIT_INDEX_FILE": os.path.join(dotgit, "index")},
        ):
            with self.subTest(env=sorted(env)):
                with mock.patch.dict(os.environ, env):
                    # Contrôle positif : sans filtre, git lit bien ailleurs.
                    self.assertNotEqual(brut, self.git_brut())
                    self.assertEqual(reference, self.lectures())


class TestUneLectureNeReecritPasLIndex(unittest.TestCase):
    """Un fichier suivi dont la date a bougé sans que son contenu change :
    `git status` rafraîchit alors d'office le cache de l'index, et le
    réécrit sous le verrou `index.lock` qu'une synchronisation concurrente
    attend. Les lectures du moteur laissent l'index tel quel."""

    def setUp(self):
        self.moteur = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", self.moteur])
        self.epingle = depot(self.moteur)
        suivi = os.path.join(self.moteur, "a")
        vu = os.stat(suivi)
        # Cinq secondes plus tard, sans attendre : la date en cache périme.
        os.utime(suivi, ns=(vu.st_atime_ns, vu.st_mtime_ns + 5_000_000_000))
        self.index = os.path.join(self.moteur, ".git", "index")

    def empreinte(self):
        """Contenu, date et inode de l'index : une réécriture au contenu
        identique change encore la date, et le renommage du verrou
        l'inode."""
        vu = os.stat(self.index)
        with open(self.index, "rb") as f:
            contenu = hashlib.sha256(f.read()).hexdigest()
        return contenu, vu.st_mtime_ns, vu.st_ino

    def test_the_readings_leave_the_index_untouched(self):
        avant = self.empreinte()
        self.assertEqual(0, engine.dirty_count(self.moteur))
        self.assertEqual(
            (engine.EGAL, 0), engine.relation_to_pin(self.moteur, self.epingle)
        )
        self.assertEqual(avant, self.empreinte())
        self.assertFalse(os.path.lexists(self.index + ".lock"))
        # Contrôle positif : la même question, posée sans retenue, réécrit
        # l'index de ce dépôt.
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        subprocess.run(
            ["git", "-C", self.moteur, "status", "--porcelain"],
            env=env,
            capture_output=True,
            check=True,
        )
        self.assertNotEqual(avant, self.empreinte())


class TestUnClonePartielNeRapatrieRien(unittest.TestCase):
    """Dans un clone partiel, git va chercher chez le remote promettant
    l'objet qu'il ne trouve pas : interroger une épingle absente serait un
    appel réseau. Les lectures du moteur n'en font aucun, et l'épingle
    reste absente.

    Le remote promettant est un dépôt local, joint par « file:// » : le
    rapatriement se constate sans réseau.
    """

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", self.dossier])
        source = os.path.join(self.dossier, "source")
        depot(source)
        git(source, "config", "uploadpack.allowFilter", "true")
        git(source, "config", "uploadpack.allowAnySHA1InWant", "true")
        self.clone = os.path.join(self.dossier, "clone")
        git(
            self.dossier,
            "clone",
            "-q",
            "--filter=blob:none",
            "--no-checkout",
            "file://" + source,
            self.clone,
        )
        self.epingle = commit(source, "b")

    def cat_file(self, **env):
        """Le code de « cat-file -e » sur l'épingle, dans le clone, sous
        l'environnement sans `GIT_*` complété de `env`."""
        propre = {
            k: v for k, v in os.environ.items() if not k.startswith("GIT_")
        }
        propre.update(env)
        return subprocess.run(
            ["git", "-C", self.clone, "cat-file", "-e", self.epingle],
            capture_output=True,
            env=propre,
        ).returncode

    def test_an_absent_pin_is_never_fetched(self):
        if self.cat_file(GIT_NO_LAZY_FETCH="1") == 0:
            self.skipTest("ce git rapatrie malgré GIT_NO_LAZY_FETCH (< 2.45)")
        self.assertEqual(
            (engine.ABSENTE, None),
            engine.relation_to_pin(self.clone, self.epingle),
        )
        self.assertEqual(
            1, self.cat_file(GIT_NO_LAZY_FETCH="1"), "épingle rapatriée"
        )
        # Contrôle positif : sans interdiction, git la rapatrie bien.
        self.assertEqual(0, self.cat_file())


class TestParentIsIgnored(unittest.TestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", self.racine])
        depot(self.racine)
        with open(os.path.join(self.racine, ".gitignore"), "w") as f:
            f.write("private/repo/\n")

    def test_a_sibling_under_an_ignored_parent_is_ignored(self):
        self.assertIs(True, engine.parent_is_ignored(self.racine, CHEMIN))

    def test_the_parent_need_not_exist_on_disk(self):
        # Un clone neuf n'a pas encore le dossier : la règle vaut quand
        # même pour ce qui y sera posé.
        self.assertFalse(
            os.path.exists(os.path.join(self.racine, "private", "repo"))
        )
        self.assertIs(True, engine.parent_is_ignored(self.racine, CHEMIN))

    def test_a_tracked_parent_is_not_ignored(self):
        self.assertIs(
            False,
            engine.parent_is_ignored(self.racine, "script/Moteur-Invente"),
        )

    def test_outside_any_repository_it_is_unknown(self):
        with tempfile.TemporaryDirectory() as ailleurs:
            self.assertIsNone(engine.parent_is_ignored(ailleurs, CHEMIN))


# Des chemins de moteur avec et sans parent, écrits normalisés ou non.
CHEMINS_SONDES = (
    CHEMIN,
    "Moteur-Invente",
    "depots/./Moteur-Invente",
    "depots//profond/Moteur-Invente",
)


class TestIgnoreProbe(unittest.TestCase):
    """UNE définition du chemin sondé, que le verdict et la source de
    l'écran partagent."""

    def test_the_probe_is_a_sibling_under_the_parent(self):
        for chemin in CHEMINS_SONDES:
            with self.subTest(chemin=chemin):
                normal = os.path.normpath(chemin)
                sonde = engine.ignore_probe(chemin)
                self.assertEqual(
                    os.path.dirname(normal), os.path.dirname(sonde)
                )
                self.assertNotEqual(normal, sonde)

    def test_the_verdict_asks_git_about_the_probe(self):
        """Le chemin que `parent_is_ignored` soumet à git est la sonde, et
        seulement elle."""
        questions = []

        def git_espion(racine, *args):
            questions.append(args)
            return None

        for chemin in CHEMINS_SONDES:
            with self.subTest(chemin=chemin):
                questions.clear()
                with mock.patch.object(engine, "_git", git_espion):
                    engine.parent_is_ignored("/racine-inventee", chemin)
                self.assertEqual(1, len(questions), questions)
                self.assertEqual(engine.ignore_probe(chemin), questions[0][-1])


PAQUET_README = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "script",
    "setops",
    "README.base.md",
)
_MARQUEUR_MMG = re.compile(r"^<!-- \[(\w+)\] -->$", re.M)


def listes_du_module_engine():
    """{langue: (texte seul, les autres)} : les deux listes à puces de la
    section `engine` de chaque langue du README du paquet, chacune en noms
    de fonctions, dans l'ordre de la page."""
    with open(PAQUET_README, encoding="utf-8") as f:
        morceaux = _MARQUEUR_MMG.split(f.read())
    rendu = {}
    for langue, bloc in zip(morceaux[1::2], morceaux[2::2]):
        if langue not in ("en", "fr"):
            continue
        (section,) = [
            s for s in bloc.split("\n## ") if s.startswith("`engine`")
        ]
        rendu[langue] = tuple(
            tuple(re.findall(r"^- `(\w+)\(", paragraphe, re.M))
            for paragraphe in section.split("\n\n")
            if paragraphe.startswith("- `")
        )
    return rendu


class ToucheLeSysteme(BaseException):
    """Levée par tout accès au disque ou à un processus pendant l'épreuve.
    Hors de `Exception`, pour qu'aucun `except` des fonctions ne l'avale."""


class TestCeQuiNeTravailleQueSurDuTexte(unittest.TestCase):
    """Le README range les fonctions d'`engine` en deux listes : celles qui
    ne travaillent que sur du texte, et les autres, qui lisent le disque ou
    lancent git. Le rangement se VÉRIFIE : chaque fonction tourne avec le
    disque et les processus interdits, sur des arguments qui la mènent
    jusqu'à ses accès."""

    # Un texte de manifeste, un chemin, un SHA complet, une liste de
    # groupes : chaque fonction reçoit toutes leurs combinaisons.
    ARGUMENTS = (manifeste(projet()), CHEMIN, SHA_INVENTE, "odoo, setops")
    INTERDITS = (
        "builtins.open",
        "io.open",
        "os.open",
        "os.stat",
        "os.lstat",
        "os.listdir",
        "os.scandir",
        "os.readlink",
        "os.getcwd",
        "subprocess.run",
        "subprocess.Popen",
    )

    def acces(self, fonction):
        """Le premier accès au système que fait `fonction`, ou None."""

        def interdit(nom):
            def leve(*_args, **_kwargs):
                raise ToucheLeSysteme(nom)

            return leve

        arite = len(inspect.signature(fonction).parameters)
        with contextlib.ExitStack() as pile:
            for cible in self.INTERDITS:
                pile.enter_context(mock.patch(cible, interdit(cible)))
            for args in itertools.product(self.ARGUMENTS, repeat=arite):
                try:
                    fonction(*args)
                except ToucheLeSysteme as refus:
                    return str(refus)
        return None

    def test_the_two_lists_sort_the_functions_by_what_they_do(self):
        listes = listes_du_module_engine()
        self.assertEqual({"en", "fr"}, set(listes))
        self.assertEqual(listes["en"], listes["fr"])
        self.assertEqual(2, len(listes["en"]), listes["en"])
        texte_seul, autres = listes["en"]
        self.assertTrue(texte_seul and autres, listes["en"])
        for nom in texte_seul + autres:
            with self.subTest(fonction=nom):
                acces = self.acces(getattr(engine, nom))
                if nom in texte_seul:
                    self.assertIsNone(acces)
                else:
                    self.assertIsNotNone(acces, "ne touche à rien")


class TestVerifierEmplacement(unittest.TestCase):
    """Le verdict que lit le script de rapatriement, par son code."""

    def setUp(self):
        self.racine = self.racine_neuve()

    def racine_neuve(self):
        """Un dossier qui porte le manifeste inventé, et rien d'autre."""
        racine = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", racine])
        os.makedirs(os.path.join(racine, "manifest"))
        with open(
            os.path.join(racine, engine.MANIFEST), "w", encoding="utf-8"
        ) as f:
            f.write(manifeste(projet()))
        return racine

    def lancer(self, action, racine=None):
        out, err = io.StringIO(), io.StringIO()
        rc = engine.main(
            [action], racine=racine or self.racine, out=out, err=err
        )
        return rc, out.getvalue(), err.getvalue()

    @staticmethod
    def occuper_le_chemin(racine):
        """Un travail en cours au chemin du moteur ; rend son fichier."""
        occupe = os.path.join(racine, CHEMIN)
        os.makedirs(occupe)
        travail = os.path.join(occupe, "travail")
        with open(travail, "w") as f:
            f.write("x")
        return travail

    def test_a_free_path_passes(self):
        self.assertEqual(0, self.lancer("verifier-emplacement")[0])

    def test_a_manual_clone_is_refused_and_the_way_out_named(self):
        travail = self.occuper_le_chemin(self.racine)
        rc, _out, err = self.lancer("verifier-emplacement")
        self.assertEqual(3, rc)
        self.assertTrue(nomme_la_mise_de_cote(err, CHEMIN), err)
        # Refuser n'est pas nettoyer : le dossier et son contenu restent.
        self.assertTrue(os.path.isfile(travail))

    def test_every_state_where_repo_does_not_manage_the_path_refuses(self):
        # Un poste déjà initialisé par repo est le cas ordinaire : il a un
        # .repo/, et sa liste ne nomme pas le chemin. Aucun de ces états ne
        # vaut « géré ».
        def liste(racine, texte):
            os.makedirs(os.path.join(racine, ".repo"))
            with open(os.path.join(racine, ".repo", "project.list"), "w") as f:
                f.write(texte)

        etats = {
            "sans .repo/": lambda racine: None,
            ".repo/ sans liste": lambda racine: os.makedirs(
                os.path.join(racine, ".repo")
            ),
            "liste d'un autre chemin": lambda racine: liste(
                racine, "addons/Autre_Invente\n"
            ),
            "liste illisible": lambda racine: os.makedirs(
                os.path.join(racine, ".repo", "project.list")
            ),
        }
        for nom, poser in etats.items():
            with self.subTest(etat=nom):
                racine = self.racine_neuve()
                poser(racine)
                travail = self.occuper_le_chemin(racine)
                rc, _out, err = self.lancer("verifier-emplacement", racine)
                self.assertEqual(engine.RC_OCCUPE, rc, err)
                self.assertTrue(nomme_la_mise_de_cote(err, CHEMIN), err)
                self.assertTrue(os.path.isfile(travail))

    def lister_le_chemin(self, racine):
        os.makedirs(os.path.join(racine, ".repo"), exist_ok=True)
        with open(os.path.join(racine, ".repo", "project.list"), "w") as f:
            f.write(CHEMIN + "\n")

    def test_a_folder_repo_already_manages_passes(self):
        self.lister_le_chemin(self.racine)
        arbre = os.path.join(self.racine, CHEMIN)
        depot_repo = os.path.join(self.racine, ".repo", "projects", CHEMIN)
        os.makedirs(arbre)
        os.makedirs(depot_repo + ".git")
        os.symlink(
            os.path.relpath(depot_repo + ".git", arbre),
            os.path.join(arbre, ".git"),
        )
        self.assertEqual(0, self.lancer("verifier-emplacement")[0])

    def test_a_listed_path_that_repo_did_not_lay_out_refuses(self):
        # La liste dit ce que le dernier sync visait, pas ce que repo a
        # extrait : un sync en échec l'écrit quand même. Un clone manuel,
        # ou un dossier sans .git, occupe alors un chemin listé.
        etats = {
            "vrai dépôt git": lambda arbre: git(arbre, "init", "-q"),
            "sans .git": lambda arbre: None,
        }
        for nom, poser in etats.items():
            with self.subTest(etat=nom):
                racine = self.racine_neuve()
                self.lister_le_chemin(racine)
                travail = self.occuper_le_chemin(racine)
                poser(os.path.dirname(travail))
                rc, _out, err = self.lancer("verifier-emplacement", racine)
                self.assertEqual(engine.RC_OCCUPE, rc, err)
                self.assertTrue(nomme_la_mise_de_cote(err, CHEMIN), err)
                self.assertTrue(os.path.isfile(travail))

    def test_a_folder_without_git_is_told_repo_would_write_over_it(self):
        # Sans .git, repo ne refuse pas : il pose son dépôt et extrait sa
        # révision sur les fichiers présents. Le refus nomme ce danger-là,
        # que le chemin soit listé ou non.
        for inscrit in (False, True):
            with self.subTest(liste=inscrit):
                racine = self.racine_neuve()
                if inscrit:
                    self.lister_le_chemin(racine)
                self.occuper_le_chemin(racine)
                rc, _out, err = self.lancer("verifier-emplacement", racine)
                self.assertEqual(engine.RC_OCCUPE, rc, err)
                self.assertTrue(annonce_l_ecrasement(err), err)

    def test_an_occupant_that_is_not_plainly_repos_refuses(self):
        """Le chemin n'est à repo que LISTÉ ET posé par lui, lu sans doute :
        un lien brisé occupe le chemin, un « gitdir: » illisible ne prouve
        rien, et un arbre que repo a posé à un chemin que sa liste ne porte
        pas n'est pas à lui."""

        def lien_brise(racine, arbre):
            os.makedirs(os.path.dirname(arbre))
            os.symlink("cible-absente-inventee", arbre)

        def gitdir_illisible(racine, arbre):
            self.lister_le_chemin(racine)
            os.makedirs(arbre)
            # Des octets qu'aucune lecture en UTF-8 n'accepte : l'épreuve
            # vaut aussi sous root, que des droits retirés n'arrêtent pas.
            with open(os.path.join(arbre, ".git"), "wb") as f:
                f.write(b"gitdir: \xff\xfe\n")

        def pose_hors_liste(racine, arbre):
            os.makedirs(os.path.join(racine, ".repo"))
            with open(os.path.join(racine, ".repo", "project.list"), "w") as f:
                f.write("addons/Autre_Invente\n")
            depot_repo = os.path.join(racine, ".repo", "projects", "x.git")
            os.makedirs(depot_repo)
            os.makedirs(arbre)
            os.symlink(
                os.path.relpath(depot_repo, arbre), os.path.join(arbre, ".git")
            )

        for nom, poser in (
            ("lien brisé", lien_brise),
            ("gitdir illisible, chemin listé", gitdir_illisible),
            ("posé par repo, non listé", pose_hors_liste),
        ):
            with self.subTest(etat=nom):
                racine = self.racine_neuve()
                arbre = os.path.join(racine, CHEMIN)
                poser(racine, arbre)
                rc, _out, err = self.lancer("verifier-emplacement", racine)
                self.assertEqual(engine.RC_OCCUPE, rc, err)
                self.assertTrue(nomme_la_mise_de_cote(err, CHEMIN), err)
                self.assertTrue(os.path.lexists(arbre))

    def test_without_a_declaration_it_stops(self):
        os.remove(os.path.join(self.racine, engine.MANIFEST))
        rc, _out, err = self.lancer("verifier-emplacement")
        self.assertNotIn(rc, (0, 3))
        self.assertIn(engine.MANIFEST, err)

    def test_chemin_prints_the_declared_path_alone(self):
        rc, out, _err = self.lancer("chemin")
        self.assertEqual((0, CHEMIN), (rc, out.strip()))

    def test_the_module_runs_as_a_program_from_the_root(self):
        # Le script shell l'appelle ainsi, depuis la racine : la racine est
        # le dossier courant, pas celui du module.
        depot_reel = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        env = dict(os.environ, PYTHONPATH=depot_reel)
        done = subprocess.run(
            [sys.executable, "-m", "script.setops.engine", "chemin"],
            cwd=self.racine,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual((0, CHEMIN), (done.returncode, done.stdout.strip()))


if __name__ == "__main__":
    unittest.main()
