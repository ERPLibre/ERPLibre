#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le manifeste du moteur Set-OPS : ses propriétés, et qui le fusionne.

Quatre choses sont éprouvées sur le VRAI manifeste du dépôt :
- où il pose le moteur : un parent ignoré par git, puisque le moteur cherche
  ses écosystèmes — des données de client — parmi ses dossiers frères ;
- sur quoi il l'épingle : un SHA complet, avec la branche d'amont qui
  borne ce que `repo sync -c` rapatrie ;
- qu'il reste SUR DEMANDE : aucune fusion par défaut ne contacte sa forge,
  le drapeau `--with_setops` l'ajoute, et l'activation automatique ne se
  fie qu'à `.repo/project.list` — un clone manuel présent ne l'allume pas ;
- qu'une fois rapatrié il le reste : toute liste de groupes que le dépôt
  passe à `repo init` le garde.

La fusion et la régénération de `manifest/default.dev.xml` tournent pour de
bon, dans un dossier temporaire qui imite la racine. Les noms qu'y posent
les épreuves sont inventés.
"""

import csv
import glob
import os
import posixpath
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from script.setops import engine

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
FUSION = os.path.join(RACINE, "script", "git", "git_merge_repo_manifest.py")
REGENERE = os.path.join(RACINE, "script", "git", "git_repo_manifest.py")

# Le chemin que les racines imitées donnent au moteur : un chemin recopié
# ailleurs que dans son manifeste ne le suit pas, et s'y voit.
CHEMIN_DEPLACE = "private/repo/Moteur-Deplace-Invente"

# Les listes que la fusion lit sans qu'on le lui demande.
LISTES_PAR_DEFAUT = (
    "git_manifest.csv",
    "git_manifest_odoo.csv",
    "git_manifest_mobile.csv",
)


def _nom(projet):
    """Le nom d'un projet sans organisation ni « .git », en minuscules."""
    nom = posixpath.basename((projet.get("name") or "").strip().rstrip("/"))
    return (nom[:-4] if nom.endswith(".git") else nom).lower()


def _forge(projet, arbre):
    """L'hôte que contacte `projet` : celui du fetch de son remote, ou du
    remote par défaut ; vide s'il ne se résout pas."""
    defaut = arbre.find("default")
    remote = projet.get("remote") or (
        defaut.get("remote") if defaut is not None else None
    )
    for r in arbre.findall("remote"):
        if r.get("name") == remote:
            return urlsplit((r.get("fetch") or "").strip()).hostname or ""
    return ""


def identite_du_moteur():
    """(forge, nom) du moteur, lus dans son manifeste."""
    arbre = ET.parse(os.path.join(RACINE, engine.MANIFEST)).getroot()
    (projet,) = [
        p
        for p in arbre.findall("project")
        if engine.GROUP in engine.groups_of(p.get("groups"))
    ]
    forge, nom = _forge(projet, arbre), _nom(projet)
    if not forge or not nom:
        raise AssertionError(f"{engine.MANIFEST} : forge ou nom illisible")
    return forge, nom


def projets_setops(chemin_xml, decl):
    """Les projets de ce fichier qui désignent le moteur, par l'un ou
    l'autre de ses traits : la forge qu'il contacte, son nom, son chemin,
    son groupe. Une déclaration posée ailleurs, sous un autre chemin et un
    autre groupe, contacte la même forge : c'est elle qu'aucune
    installation par défaut ne doit contacter."""
    try:
        arbre = ET.parse(chemin_xml).getroot()
    except (ET.ParseError, OSError):
        return []
    forge, nom = identite_du_moteur()
    return [
        p
        for p in arbre.findall("project")
        if os.path.normpath(p.get("path") or "") == decl.path
        or engine.GROUP in engine.groups_of(p.get("groups"))
        or _forge(p, arbre) == forge
        or _nom(p) == nom
    ]


def declaration_deplacee(dossier, forge=True, nom=True):
    """Écrit dans `dossier` un manifeste qui redéclare le moteur sous un
    chemin et un groupe inventés — la forme d'une déclaration posée ailleurs
    — en gardant sa forge, son nom, ou les deux ; rend son chemin.

    La forge et le nom se recopient du manifeste du moteur, jamais du texte
    de l'épreuve."""
    source = ET.parse(os.path.join(RACINE, engine.MANIFEST)).getroot()
    (projet,) = [
        p
        for p in source.findall("project")
        if engine.GROUP in engine.groups_of(p.get("groups"))
    ]
    (remote,) = [
        r
        for r in source.findall("remote")
        if r.get("name") == projet.get("remote")
    ]
    fetch = remote.get("fetch") if forge else "https://forge.exemple.invalid/"
    sortie = ET.Element("manifest")
    ET.SubElement(
        sortie, "remote", name="remote-deplacee-inventee", fetch=fetch
    )
    ET.SubElement(
        sortie,
        "project",
        name=projet.get("name") if nom else "Remote-Deplace-Invente.git",
        path="script/moteur-invente",
        remote="remote-deplacee-inventee",
        revision="main",
        groups="base",
    )
    chemin = os.path.join(dossier, "declaration-deplacee.xml")
    ET.ElementTree(sortie).write(chemin, encoding="unicode")
    return chemin


def deplacer_le_moteur(racine, chemin):
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


class TestLeVraiManifeste(unittest.TestCase):
    def setUp(self):
        self.decl = engine.declaration(RACINE)
        self.assertIsNotNone(self.decl, engine.MANIFEST)

    def test_the_engine_lands_under_an_ignored_parent(self):
        # Demandé à git, pas comparé à une chaîne : c'est la règle du
        # .gitignore qui protège les écosystèmes frères, quelle que soit
        # sa forme.
        self.assertIs(True, engine.parent_is_ignored(RACINE, self.decl.path))

    def test_the_revision_is_a_full_sha(self):
        self.assertTrue(engine.is_pinned(self.decl.revision), self.decl)

    def test_the_upstream_names_the_branch_that_carries_the_pin(self):
        # Avec une branche d'amont, « repo sync -c » ne rapatrie qu'elle ;
        # sans elle, toutes. Un SHA à sa place fait échouer la
        # synchronisation : repo le cherche comme refs/heads/<SHA>.
        self.assertTrue(self.decl.upstream)
        self.assertFalse(engine.is_pinned(self.decl.upstream))

    def test_the_pin_is_fetched_whole(self):
        # En profondeur 1, rapatrier un SHA qui n'est plus la pointe exige
        # une forge qui l'accepte ; le dépôt est petit, la profondeur
        # entière ne coûte rien.
        (projet,) = projets_setops(
            os.path.join(RACINE, engine.MANIFEST), self.decl
        )
        self.assertIsNone(projet.get("clone-depth"))


class TestAucuneFusionParDefaut(unittest.TestCase):
    """Aucune installation ne contacte la forge du moteur sans le demander."""

    def setUp(self):
        self.decl = engine.declaration(RACINE)

    def manifestes_par_defaut(self):
        vus = []
        for nom in LISTES_PAR_DEFAUT:
            with open(os.path.join(RACINE, "conf", nom)) as f:
                for ligne in csv.DictReader(f):
                    vus.append(ligne["filepath"])
        return vus

    def test_the_default_lists_are_read(self):
        # Une lecture cassée rendrait zéro fichier, et l'épreuve suivante
        # passerait sans rien regarder.
        self.assertGreaterEqual(len(self.manifestes_par_defaut()), 5)

    def test_no_default_list_names_the_engine(self):
        for chemin in self.manifestes_par_defaut():
            with self.subTest(manifeste=chemin):
                self.assertEqual(
                    [], projets_setops(os.path.join(RACINE, chemin), self.decl)
                )

    def test_no_other_manifest_of_the_repository_declares_it(self):
        # Les manifestes par version entrent aussi dans la fusion par
        # défaut, sans passer par une liste.
        autres = [
            m
            for m in glob.glob(os.path.join(RACINE, "manifest", "*.xml"))
            if os.path.relpath(m, RACINE) != engine.MANIFEST
        ]
        self.assertGreater(len(autres), 10)
        for chemin in autres:
            with self.subTest(manifeste=os.path.relpath(chemin, RACINE)):
                self.assertEqual([], projets_setops(chemin, self.decl))

    def test_the_detector_sees_the_engine_by_its_forge_or_its_name(self):
        # Une déclaration posée ailleurs, sous un autre chemin et un autre
        # groupe, contacte la même forge, qu'aucune installation par défaut
        # ne doit contacter.
        with tempfile.TemporaryDirectory() as dossier:
            for forge, nom in ((True, True), (True, False), (False, True)):
                with self.subTest(forge=forge, nom=nom):
                    chemin = declaration_deplacee(dossier, forge, nom)
                    self.assertEqual(1, len(projets_setops(chemin, self.decl)))
            # Contrôle négatif : ni la forge, ni le nom.
            chemin = declaration_deplacee(dossier, False, False)
            self.assertEqual([], projets_setops(chemin, self.decl))

    def test_the_detector_finds_it_where_it_is(self):
        # Contrôle positif : un détecteur qui ne voit rien passerait les
        # deux épreuves précédentes.
        self.assertEqual(
            1,
            len(
                projets_setops(
                    os.path.join(RACINE, engine.MANIFEST), self.decl
                )
            ),
        )


class RacineImitee(unittest.TestCase):
    """Un dossier temporaire qui porte les listes et les manifestes du
    dépôt, et rien d'autre : ni `.repo/`, ni moteur, ni état d'installation.
    Le manifeste du moteur y pose le moteur en `CHEMIN_DEPLACE`.
    """

    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine, True)
        shutil.copytree(
            os.path.join(RACINE, "manifest"),
            os.path.join(self.racine, "manifest"),
        )
        deplacer_le_moteur(self.racine, CHEMIN_DEPLACE)
        self.decl = engine.declaration(self.racine)
        # Contrôle : une racine qui retomberait sur le vrai manifeste ne
        # distinguerait plus un chemin recopié.
        self.assertEqual(CHEMIN_DEPLACE, self.decl.path)
        self.assertNotEqual(engine.declaration(RACINE).path, self.decl.path)
        os.makedirs(os.path.join(self.racine, "conf"))
        for liste in glob.glob(os.path.join(RACINE, "conf", "git_manifest*")):
            shutil.copy(liste, os.path.join(self.racine, "conf"))
        with open(os.path.join(self.racine, ".odoo-version"), "w") as f:
            f.write("18.0")

    def repo_gere(self, *chemins):
        os.makedirs(os.path.join(self.racine, ".repo"), exist_ok=True)
        with open(
            os.path.join(self.racine, ".repo", "project.list"), "w"
        ) as f:
            f.write("".join(c + "\n" for c in chemins))

    def clone_manuel(self, git_init=False):
        dossier = os.path.join(self.racine, self.decl.path)
        os.makedirs(dossier)
        with open(os.path.join(dossier, "README.md"), "w") as f:
            f.write("clone manuel\n")
        if git_init:
            subprocess.run(["git", "init", "-q", dossier], check=True)

    def fusion(self, *drapeaux):
        """Le projet du moteur dans le manifeste local fusionné, ou None."""
        sortie = os.path.join(self.racine, "fusion.xml")
        fait = subprocess.run(
            [sys.executable, FUSION, "--output", sortie, *drapeaux],
            cwd=self.racine,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, fait.returncode, fait.stderr[-600:])
        trouves = projets_setops(sortie, self.decl)
        self.assertLessEqual(len(trouves), 1)
        return trouves[0] if trouves else None


class TestLaFusion(RacineImitee):
    def test_the_default_merge_leaves_the_engine_out(self):
        # Le script de développement fusionne ainsi.
        self.assertIsNone(self.fusion("--with_OCA"))

    def test_the_flag_adds_it_pinned_and_with_its_upstream(self):
        projet = self.fusion("--with_OCA", "--with_setops")
        self.assertIsNotNone(projet)
        self.assertEqual(self.decl.revision, projet.get("revision"))
        # « upstream » traverse la fusion : sans lui, « repo sync -c »
        # rapatrie toutes les branches du moteur au lieu de celle qui porte
        # l'épingle.
        self.assertEqual(self.decl.upstream, projet.get("upstream"))

    def test_the_flag_alone_is_enough(self):
        self.assertIsNotNone(self.fusion("--with_setops"))

    def test_it_comes_back_by_itself_once_repo_manages_it(self):
        # Opté une fois : la fusion suivante du poste le garde, sans quoi
        # le « repo sync » de développement le déclarerait obsolète.
        self.repo_gere("addons/Autre_Invente", self.decl.path)
        self.assertIsNotNone(self.fusion("--with_OCA"))

    def test_a_manual_clone_does_not_switch_it_on(self):
        # Le dossier existe, repo ne le gère pas : l'allumer ferait échouer
        # le prochain « repo sync » sur un chemin occupé.
        self.clone_manuel()
        self.assertIsNone(self.fusion("--with_OCA"))

    def test_a_manual_clone_beside_a_real_repo_does_not_either(self):
        self.repo_gere("addons/Autre_Invente")
        self.clone_manuel()
        self.assertIsNone(self.fusion("--with_OCA"))

    def test_a_listed_path_stays_in_the_merge_whatever_occupies_it(self):
        # Un chemin que la liste porte et que la fusion lâcherait serait
        # supprimé par le sync suivant, s'il est propre — clone manuel et
        # commits non poussés compris. La liste seule décide, pas la forme
        # de ce qui occupe le chemin.
        self.repo_gere(self.decl.path)
        self.clone_manuel(git_init=True)
        self.assertIsNotNone(self.fusion("--with_OCA"))

    def test_the_default_merge_carries_what_the_extra_declares(self):
        # Contrôle positif du détecteur : une déclaration posée dans
        # le manifeste « extra », que la fusion par défaut prend, se voit
        # dans ce qu'elle produit.
        extra = os.path.join(
            self.racine, "manifest", "git_manifest_erplibre_extra.xml"
        )
        self.assertTrue(os.path.exists(extra))
        shutil.move(declaration_deplacee(self.racine), extra)
        self.assertIsNotNone(self.fusion("--with_OCA"))

    def test_a_new_manifest_never_switches_anything_on(self):
        self.repo_gere(self.decl.path)
        self.assertIsNone(self.fusion("--with_new_manifest", "--with_OCA"))


# Où le dépôt passe des listes de groupes à « repo init » : directement, ou
# par les arguments d'un script de script/manifest/.
SOURCES_DE_GROUPES = ("script/manifest/*.sh", "Makefile", "conf/*.Makefile")
# Un fichier qui passe une liste de groupes à repo : le balayage doit l'y
# trouver, ou il ne regarde plus rien.
PORTEUR_DE_GROUPES = os.path.join(
    "script", "manifest", "update_manifest_local_dev_code_generator.sh"
)


def listes_de_groupes(fichiers):
    """(fichier, liste) de chaque « -g » ou « --groups » d'une ligne qui
    lance « repo init » ou un script update_manifest_*, hors commentaire.

    Les lignes se lisent comme le shell et make les lisent : une ligne finie
    par « \\ » se poursuit sur la suivante, un commentaire de fin de ligne
    est ôté, et chaque argument se découpe selon les guillemets. La liste
    suit « -g » ou « --groups », ou leur est collée — « -gX »,
    « --groups=X », ou un argument « -g X » passé tel quel à un script.
    Elle est rendue telle qu'écrite, variable comprise, et None pour une
    ligne que le shell ne saurait découper : `lisible` en juge."""
    for fichier in fichiers:
        with open(fichier, encoding="utf-8") as f:
            logiques = f.read().replace("\\\n", " ").splitlines()
        for code in (ligne.strip() for ligne in logiques):
            if code.startswith("#"):
                continue
            if "repo init" not in code and "update_manifest_" not in code:
                continue
            try:
                mots = shlex.split(code, comments=True)
            except ValueError:
                yield fichier, None
                continue
            for i, mot in enumerate(mots):
                if mot in ("-g", "--groups"):
                    yield fichier, mots[i + 1] if i + 1 < len(mots) else ""
                elif mot.startswith(("--groups=", "--groups ")):
                    yield fichier, mot[len("--groups=") :].strip()
                elif mot.startswith("-g") and not mot.startswith("--"):
                    yield fichier, mot[2:].strip()


def lisible(liste):
    """Une liste écrite en toutes lettres : ni vide, ni variable, ni
    substitution de commande — rien que le balayage ne sache évaluer."""
    return bool(liste) and not {"$", "`"} & set(liste)


def repo_selectionne(groupes, liste):
    """La règle de Google Repo (MatchesGroups) : un projet porte aussi
    « all », et « default » faute de « notdefault » ; la dernière entrée de
    la liste qui le concerne décide, et « -x » l'écarte."""
    etendus = set(groupes) | {"all"}
    if "notdefault" not in etendus:
        etendus.add("default")
    retenu = False
    for groupe in engine.groups_of(liste):
        if groupe.startswith("-") and groupe[1:] in etendus:
            retenu = False
        elif groupe in etendus:
            retenu = True
    return retenu


def groupes_du_moteur():
    """Les groupes que Google Repo donne au moteur, lus dans son manifeste :
    les siens, plus « name:… » et « path:… »."""
    arbre = ET.parse(os.path.join(RACINE, engine.MANIFEST)).getroot()
    (projet,) = [
        p
        for p in arbre.findall("project")
        if engine.GROUP in engine.groups_of(p.get("groups"))
    ]
    return engine.groups_of(projet.get("groups")) + [
        "name:" + projet.get("name", ""),
        "path:" + projet.get("path", ""),
    ]


class TestLesListesDeGroupesGardentLeMoteur(unittest.TestCase):
    """Sur un poste opté, un sync dont les groupes écartent le moteur
    supprime son arbre s'il est propre — fichiers ignorés compris — et le
    retire de `.repo/project.list` ; les fusions suivantes le lâchent, et le
    poste est dés-opté sans rien dire. S'il porte des modifications, ce
    sync échoue à chaque fois. Toute liste de groupes que le dépôt passe à
    repo garde donc le moteur."""

    def test_every_group_list_the_repository_passes_keeps_the_engine(self):
        fichiers = [
            f
            for motif in SOURCES_DE_GROUPES
            for f in sorted(glob.glob(os.path.join(RACINE, motif)))
        ]
        trouvees = list(listes_de_groupes(fichiers))
        # Plancher : une réécriture que le balayage ne lit plus le laisserait
        # vert sans avoir rien regardé.
        self.assertIn(
            PORTEUR_DE_GROUPES,
            [os.path.relpath(f, RACINE) for f, _liste in trouvees],
            trouvees,
        )
        groupes = groupes_du_moteur()
        for fichier, liste in trouvees:
            with self.subTest(fichier=os.path.relpath(fichier, RACINE)):
                self.assertTrue(
                    lisible(liste),
                    f"liste illisible, {liste!r} : l'écrire en toutes lettres",
                )
                self.assertTrue(repo_selectionne(groupes, liste), liste)

    def test_the_scanner_reads_what_a_script_passes(self):
        # Contrôle positif : un balayage qui ne voit rien passerait
        # l'épreuve précédente. Chaque écriture qu'accepte repo se lit ; ce
        # qui ne s'évalue pas sans lancer le shell se dit illisible.
        with tempfile.TemporaryDirectory() as dossier:
            script = os.path.join(dossier, "script-invente.sh")
            with open(script, "w", encoding="utf-8") as f:
                f.write(
                    "# repo init -g commente,invente\n"
                    "repo init -u x -m y -g base,invente\n"
                    "\t./script/manifest/update_manifest_invente.sh"
                    ' "--groups=autre,invente"\n'
                    "echo -g sans-rapport\n"
                    "repo init -u x -gcolle,invente\n"
                    'repo init -u x -g "cite,invente"\n'
                    'repo init -u x --groups "longue,invente"\n'
                    "repo init -u x \\\n  -g suite,invente\n"
                    "./script/manifest/update_manifest_invente.sh"
                    ' "-g argument,invente"\n'
                    "repo init -u x -g fin,invente  # l'ancienne : -g base\n"
                    "./script/manifest/update_manifest_invente.sh"
                    "  # rafraîchit l'arbre\n"
                    'repo init -u x -g "${LISTE_INVENTEE}"\n'
                    "repo init -u x -g 'ouverte,invente\n"
                )
            listes = [liste for _f, liste in listes_de_groupes([script])]
        self.assertEqual(
            [
                "base,invente",
                "autre,invente",
                "colle,invente",
                "cite,invente",
                "longue,invente",
                "suite,invente",
                "argument,invente",
                "fin,invente",
                "${LISTE_INVENTEE}",
                None,
            ],
            listes,
        )
        self.assertEqual(
            [True] * 8 + [False, False], [lisible(liste) for liste in listes]
        )

    def test_the_rule_is_that_of_google_repo(self):
        moteur = ["setops"]
        self.assertFalse(repo_selectionne(moteur, "base,code_generator"))
        self.assertTrue(repo_selectionne(moteur, "base,setops"))
        self.assertTrue(repo_selectionne(moteur, "default"))
        self.assertTrue(repo_selectionne(moteur, "all"))
        self.assertFalse(repo_selectionne(moteur, "all,-setops"))
        self.assertTrue(repo_selectionne(moteur, "-setops,setops"))
        self.assertFalse(repo_selectionne(moteur + ["notdefault"], "default"))


class TestLaRegenerationDuManifesteDeDeveloppement(unittest.TestCase):
    """`git_repo_manifest.py` réécrit `manifest/default.dev.xml` en y
    reportant les projets du manifeste LOCAL fusionné — celui d'un poste
    opté porte le moteur. Le fichier régénéré reprend ce manifeste moins le
    groupe sur demande : le moteur, et la forge qui ne sert que lui, n'y
    entrent pas ; les autres projets du poste, si."""

    AUTRE_FORGE = "https://forge.exemple.invalid/Autre-Inventee/"

    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine, True)
        subprocess.run(["git", "init", "-q", self.racine], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                self.racine,
                "remote",
                "add",
                "origin",
                "https://forge.exemple.invalid/Orga-Inventee/Racine.git",
            ],
            check=True,
        )
        with open(os.path.join(self.racine, ".odoo-version"), "w") as f:
            f.write("18.0")
        with open(
            os.path.join(self.racine, "source_repo_addons.csv"), "w"
        ) as f:
            f.write(
                "url,path,revision,clone-depth\n"
                "https://forge.exemple.invalid/Orga-Inventee/Addon.git"
                ",addons,,\n"
            )
        os.makedirs(os.path.join(self.racine, "script"))
        shutil.copy(
            os.path.join(RACINE, "script", "generate_config.sh"),
            os.path.join(self.racine, "script"),
        )
        with open(os.path.join(RACINE, engine.MANIFEST)) as f:
            setops = ET.fromstring(f.read())
        local = ET.Element("manifest")
        for remote in setops.findall("remote"):
            local.append(remote)
        ET.SubElement(
            local, "remote", name="autre-inventee", fetch=self.AUTRE_FORGE
        )
        for projet in setops.findall("project"):
            local.append(projet)
        ET.SubElement(
            local,
            "project",
            name="Addon-Garde.git",
            path="addons/Autre_Garde",
            remote="autre-inventee",
            revision="18.0",
            groups="addons,odoo18.0",
        )
        self.remotes_setops = [r.get("name") for r in setops.findall("remote")]
        dossier = os.path.join(self.racine, ".repo", "local_manifests")
        os.makedirs(dossier)
        ET.ElementTree(local).write(
            os.path.join(dossier, "erplibre_manifest.xml"),
            encoding="unicode",
        )

    def regenerer(self):
        fait = subprocess.run(
            [sys.executable, REGENERE],
            cwd=self.racine,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, fait.returncode, fait.stderr[-600:])
        return ET.parse(
            os.path.join(self.racine, "manifest", "default.dev.xml")
        ).getroot()

    def test_the_engine_stays_out_of_the_regenerated_manifest(self):
        decl = engine.declaration(RACINE)
        produit = self.regenerer()
        chemins = [p.get("path") for p in produit.findall("project")]
        self.assertNotIn(decl.path, chemins)
        self.assertNotIn(
            engine.GROUP,
            [p.get("groups") for p in produit.findall("project")],
        )

    def test_its_forge_goes_with_it(self):
        noms = [r.get("name") for r in self.regenerer().findall("remote")]
        for remote in self.remotes_setops:
            self.assertNotIn(remote, noms)

    def test_the_other_projects_and_their_forge_are_kept(self):
        # Contrôle positif : tout jeter passerait les deux précédentes.
        produit = self.regenerer()
        self.assertIn(
            "addons/Autre_Garde",
            [p.get("path") for p in produit.findall("project")],
        )
        self.assertIn(
            "autre-inventee",
            [r.get("name") for r in produit.findall("remote")],
        )


class TestDropGroup(unittest.TestCase):
    """Le tri lui-même, sur la forme que rend `get_manifest_xml_info`."""

    def test_a_remote_shared_with_a_kept_project_stays(self):
        from script.git.git_repo_manifest import drop_group

        remotes = {
            "partagee": {"@name": "partagee", "@fetch": "https://x.invalid/"},
            "seule": {"@name": "seule", "@fetch": "https://y.invalid/"},
        }
        projects = {
            "a": {"@name": "a", "@remote": "partagee", "@groups": "setops"},
            "b": {"@name": "b", "@remote": "partagee", "@groups": "addons"},
            "c": {"@name": "c", "@remote": "seule", "@groups": "x, setops"},
        }
        restes, gardes = drop_group(remotes, projects, "setops")
        self.assertEqual(["b"], sorted(gardes))
        self.assertEqual(["partagee"], sorted(restes))

    def test_every_list_form_repo_splits_is_dropped(self):
        from script.git.git_repo_manifest import drop_group

        # Les formes que Google Repo découpe en « setops » et autre chose ;
        # un nom qui ne fait que le contenir est un autre groupe.
        formes = ("setops", "odoo,setops", "odoo, setops", "odoo setops")
        for forme in formes + ("setopsx", "odoo,mysetops"):
            with self.subTest(groups=forme):
                projects = {"p": {"@remote": "r", "@groups": forme}}
                _restes, gardes = drop_group({}, projects, engine.GROUP)
                attendu = [] if forme in formes else ["p"]
                self.assertEqual(attendu, sorted(gardes))


if __name__ == "__main__":
    unittest.main()
