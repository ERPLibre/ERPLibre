#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran « Set-OPS › État de l'intégration », éprouvé sans le moteur.

Les décisions se lisent sur des relevés POSÉS : c'est ce qui permet
d'éprouver l'état d'un poste qu'on n'a pas sous la main, et les verdicts
qu'on ne sait pas provoquer ici. Le relevé lui-même se confronte à un FAUX
moteur, dans un dossier temporaire : liens `instance` et `underlay.yml`,
faux `scripts/voutes.py`, faux venv. Le vrai moteur n'est lu que par une
épreuve, qui se dit ignorée sans lui : il est absent en CI, `private/repo/`
étant ignoré par git.

Les noms de moteur, d'écosystème, de site et de variable sont inventés et
n'existent nulle part ailleurs dans le dépôt.
"""

import fnmatch
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.setops import ansible_env, ecosystems, engine  # noqa: E402
from script.setops import state as S  # noqa: E402
from script.todo import devstack_state, state_screen, todo_i18n  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

RACINE_DEPOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

CHEMIN = "private/repo/Moteur-Fictif-Granit"
SHA = "fedcba9876543210fedcba9876543210fedcba98"
ECOSYSTEME = "Ecosysteme-Fictif-Quartz"
SITE = "Site-Fictif-Basalte"
PLAGE = "ansible-core>=2.18,<2.19"
# Le dossier frère qu'une épreuve met à la place du repère d'un geste.
FRERE_REJOUE = "Site-Fictif-Olivine"

# L'ordre attendu, écrit ici en entier : c'est la spécification que
# l'écran doit tenir, et non une copie de la constante qu'il éprouve.
ORDRE_SPECIFIE = (
    "Platform",
    "Engine manifest",
    "Private location",
    "Google Repo",
    "Engine",
    "Ansible environment",
    "Mounted ecosystem",
    "Mounted site",
    "Ecosystem vault key",
    "Station tools",
)


def regle(**remplace):
    """Un relevé de banc ENTIÈREMENT réglé, sauf ce qu'on remplace."""
    base = dict(
        systeme="Linux",
        chemin=CHEMIN,
        revision=SHA,
        parent_ignore=True,
        outil_repo=True,
        repo_initialise=True,
        chemin_occupe=True,
        moteur_present=True,
        gere_par_repo=True,
        arbre_repo=True,
        relation=engine.EGAL,
        ecart=0,
        modifies=0,
        ansible_playbook=True,
        version_ansible="2.18.6",
        plage_ansible=PLAGE,
        mineur_path=ansible_env.MINEUR_CIBLE,
        biblios_ecarts=(),
        collections_ecarts=(),
        biblios_epinglees=(("proxmoxer", "2.2.0"),),
        collections_epinglees=(("community.general", "10.3.0"),),
        instance_reelle=False,
        ecosysteme=ECOSYSTEME,
        plan_present=True,
        site=SITE,
        site_brise=False,
        code_cle=0,
        outils_absents=(),
    )
    base.update(remplace)
    return S.Releve(**base)


def vide():
    """Le relevé d'un poste où rien n'est posé ni lisible."""
    return S.Releve(
        systeme="",
        chemin="",
        revision="",
        parent_ignore=None,
        outil_repo=False,
        repo_initialise=False,
        chemin_occupe=False,
        moteur_present=False,
        gere_par_repo=None,
        arbre_repo=None,
        relation=engine.INCONNUE,
        ecart=None,
        modifies=None,
        ansible_playbook=False,
        version_ansible=None,
        plage_ansible=None,
        mineur_path=None,
        biblios_ecarts=(),
        collections_ecarts=(),
        biblios_epinglees=None,
        collections_epinglees=None,
        instance_reelle=False,
        ecosysteme="",
        plan_present=False,
        site="",
        site_brise=False,
        code_cle=None,
        outils_absents=tuple(S.OUTILS_COEUR)
        + tuple(o for o, _ in S.OUTILS_GESTES),
    )


def ligne(vu, segment):
    """La ligne d'un segment, désignée par sa clé anglaise."""
    rendu = S.lignes(vu)
    return rendu[S.SEGMENTS.index(segment)]


class CasDeLangue(unittest.TestCase):
    """La langue est ÉPINGLÉE : les clés SONT les chaînes anglaises."""

    LANGUE = "en"

    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = self.LANGUE


class TestUnRenduPourDeuxEcrans(CasDeLangue):
    """Deux écrans d'état, un seul rendu : une marque, un compte, une
    colonne qui divergeraient d'un écran à l'autre diraient deux choses
    différentes avec les mêmes signes."""

    def test_devstack_renders_through_the_shared_function(self):
        self.assertIs(state_screen.render, devstack_state.render)
        self.assertIs(state_screen.Ligne, devstack_state.Ligne)
        self.assertEqual(state_screen.MARQUES, devstack_state.MARQUES)

    def test_setops_lines_are_the_shared_line(self):
        for rendu in (S.lignes(regle()), S.lignes(vide())):
            for l in rendu:
                with self.subTest(segment=l.segment):
                    self.assertIsInstance(l, state_screen.Ligne)
                    self.assertIn(l.etat, state_screen.ETATS)

    def test_the_shared_render_prints_every_setops_segment(self):
        rendu = S.lignes(vide())
        texte = "\n".join(state_screen.render(rendu))
        for l in rendu:
            with self.subTest(segment=l.segment):
                self.assertIn(l.segment, texte)
                self.assertIn(l.source, texte)

    # Un rendu posé à la main, sans `lignes()` : segments, détails et
    # sources inventés et distincts, comptes inégaux.
    POSE = (
        state_screen.Ligne(
            "Segment-Fictif-Ambre", state_screen.PORTE, "detail-ambre", "a"
        ),
        state_screen.Ligne(
            "Segment-Fictif-Beryl", state_screen.A_REGLER, "detail-beryl", "b"
        ),
        state_screen.Ligne(
            "Segment-Fictif-Corail", state_screen.PORTE, "detail-corail", "c"
        ),
    )

    def test_each_row_carries_its_mark_and_its_own_detail(self):
        """La rangée d'un segment porte la marque de SON état et SON
        détail : c'est ce détail qui nomme le geste d'une ligne à régler."""
        rangs = state_screen.render(self.POSE)
        for l in self.POSE:
            with self.subTest(segment=l.segment):
                siennes = [r for r in rangs if l.segment in r and "↳" not in r]
                self.assertEqual(1, len(siennes), rangs)
                marque = state_screen.MARQUES[l.etat]
                rangee = siennes[0]
                self.assertTrue(rangee.lstrip().startswith(marque), rangee)
                self.assertIn(l.detail, rangee)

    def test_the_count_pairs_each_number_with_its_state(self):
        rangs = state_screen.render(self.POSE)
        for n, cle in (
            (2, "carried"),
            (1, "to set up here"),
            (0, "not in the repository"),
        ):
            with self.subTest(cle=cle):
                self.assertIn(f"{n} {t(cle)}", rangs[-1])


class TestLesDixSegments(CasDeLangue):
    def test_ten_segments_in_the_specified_order(self):
        self.assertEqual(ORDRE_SPECIFIE, tuple(S.SEGMENTS))
        for vu in (regle(), vide()):
            self.assertEqual(
                list(ORDRE_SPECIFIE), [l.segment for l in S.lignes(vu)]
            )

    def test_every_line_cites_a_source(self):
        """Sans origine, la ligne est une affirmation de plus : personne ne
        peut la contredire sans lire le module qui la rend. Une source qui
        garde un gabarit non rempli ne se rejoue pas ; celle d'une ligne
        qui lit dans le moteur nomme le chemin déclaré, ou le repère du
        moteur sans déclaration."""

        def lit_le_moteur(segment):
            while segment is not None:
                if segment == S.MOTEUR:
                    return True
                segment = (S.PREALABLES.get(segment) or (None,))[0]
            return False

        for nom, vu in (("regle", regle()), ("vide", vide())):
            for segment, l in zip(S.SEGMENTS, S.lignes(vu)):
                with self.subTest(releve=nom, segment=l.segment):
                    self.assertTrue(l.source.strip())
                    self.assertNotIn("{", l.source)
                    if lit_le_moteur(segment):
                        self.assertIn(vu.chemin or t(S.MOTEUR), l.source)

    def test_every_line_says_something(self):
        for nom, vu in (("regle", regle()), ("vide", vide())):
            for l in S.lignes(vu):
                with self.subTest(releve=nom, segment=l.segment):
                    self.assertTrue(l.detail.strip())


class TestSegmentsTraduits(CasDeLangue):
    LANGUE = "fr"

    def test_segment_labels_follow_the_language(self):
        vus = [l.segment for l in S.lignes(regle())]
        self.assertEqual(
            [todo_i18n.TRANSLATIONS[s]["fr"] for s in ORDRE_SPECIFIE], vus
        )


class TestControlePositif(CasDeLangue):
    """Prouve que les gardes SAVENT être vertes : refuser toujours
    passerait toutes les épreuves de refus ci-dessous."""

    def test_a_fully_settled_survey_carries_all_ten(self):
        self.assertEqual(
            [state_screen.PORTE] * 10,
            [l.etat for l in S.lignes(regle())],
        )


class TestPlateforme(CasDeLangue):
    def test_another_system_is_absent_and_named(self):
        l = ligne(regle(systeme="Darwin"), "Platform")
        self.assertEqual(state_screen.ABSENT, l.etat)
        self.assertIn("Darwin", l.detail)


class TestManifeste(CasDeLangue):
    def test_no_declaration_is_absent(self):
        l = ligne(regle(chemin="", revision=""), "Engine manifest")
        self.assertEqual(state_screen.ABSENT, l.etat)

    def test_an_unpinned_revision_is_absent_and_named(self):
        """Une branche désigne demain autre chose qu'aujourd'hui."""
        for revision in ("main", SHA[:12], ""):
            with self.subTest(revision=revision):
                l = ligne(regle(revision=revision), "Engine manifest")
                self.assertEqual(state_screen.ABSENT, l.etat)
                self.assertIn(f"« {revision} »", l.detail)

    def test_a_pinned_revision_names_the_path(self):
        l = ligne(regle(), "Engine manifest")
        self.assertEqual(state_screen.PORTE, l.etat)
        self.assertIn(CHEMIN, l.detail)
        self.assertIn(SHA[:7], l.detail)


class TestEmplacementPrive(CasDeLangue):
    def test_a_parent_not_ignored_is_absent_and_says_so(self):
        l = ligne(regle(parent_ignore=False), "Private location")
        self.assertEqual(state_screen.ABSENT, l.etat)
        self.assertIn("NOT ignored", l.detail)
        self.assertIn(os.path.dirname(CHEMIN), l.detail)

    def test_an_unknown_answer_is_never_carried(self):
        l = ligne(regle(parent_ignore=None), "Private location")
        self.assertEqual(state_screen.ABSENT, l.etat)

    def test_without_declaration_nothing_is_carried(self):
        l = ligne(
            regle(chemin="", revision="", parent_ignore=None),
            "Private location",
        )
        self.assertNotEqual(state_screen.PORTE, l.etat)

    def test_the_line_names_the_parent_never_the_engine(self):
        """C'est le parent que git doit ignorer : les écosystèmes se posent
        à côté du moteur, pas dedans."""
        for reponse in (True, False, None):
            with self.subTest(parent_ignore=reponse):
                l = ligne(regle(parent_ignore=reponse), "Private location")
                self.assertIn(os.path.dirname(CHEMIN) + "/", l.detail)
                self.assertNotIn(CHEMIN, l.detail)


class TestGoogleRepo(CasDeLangue):
    def test_each_missing_piece_names_its_gesture(self):
        cas = (
            ({"outil_repo": False}, (S.INSTALLER_REPO,)),
            ({"repo_initialise": False}, (S.RAPATRIER,)),
            (
                {"outil_repo": False, "repo_initialise": False},
                (S.INSTALLER_REPO, S.RAPATRIER),
            ),
        )
        for manque, gestes in cas:
            with self.subTest(**manque):
                l = ligne(regle(**manque), "Google Repo")
                self.assertEqual(state_screen.A_REGLER, l.etat)
                for geste in gestes:
                    self.assertIn(geste, l.detail)

    def test_a_manual_clone_is_set_aside_before_initializing(self):
        """Le script de rapatriement refuse un chemin occupé par un clone
        que Google Repo ne gère pas : le geste qui initialise `.repo/` ne
        part qu'une fois le clone mis de côté, et la ligne les nomme dans
        cet ordre."""
        mv = engine.mise_de_cote(CHEMIN)
        l = ligne(
            regle(repo_initialise=False, gere_par_repo=None), "Google Repo"
        )
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertIn(mv, l.detail)
        self.assertIn(S.RAPATRIER, l.detail)
        self.assertLess(l.detail.index(mv), l.detail.index(S.RAPATRIER))

    def test_without_engine_the_script_alone_initializes(self):
        """Contrôle positif : sans clone à mettre de côté, la ligne ne
        nomme aucun déplacement."""
        l = ligne(
            regle(
                repo_initialise=False,
                gere_par_repo=None,
                chemin_occupe=False,
                moteur_present=False,
                arbre_repo=None,
            ),
            "Google Repo",
        )
        self.assertIn(S.RAPATRIER, l.detail)
        self.assertNotIn(engine.mise_de_cote(CHEMIN), l.detail)
        self.assertIn(
            t(".repo/ not initialized: {cmd} initializes it").format(
                cmd=S.RAPATRIER
            ),
            l.detail,
        )

    def test_the_named_gestures_exist_in_the_repository(self):
        """Un geste nommé qui n'existe pas enverrait chercher un fichier
        que personne ne trouvera."""
        for geste in (S.INSTALLER_REPO, S.RAPATRIER):
            with self.subTest(geste=geste):
                self.assertTrue(
                    os.path.isfile(os.path.join(RACINE_DEPOT, geste))
                )


class TestMoteur(CasDeLangue):
    MV = f"mv {CHEMIN} {CHEMIN}.manuel"

    def test_a_manual_clone_is_never_carried_and_names_the_move(self):
        """Sans `.repo/`, rien ne gère le dossier ; avec, la liste des
        projets peut l'ignorer, ou le porter sans que repo ait posé l'arbre
        — il écrit sa liste même quand le rapatriement échoue. Tous sont un
        clone manuel, et le prochain `repo sync` refuserait le chemin
        occupé."""
        for manque in (
            {"repo_initialise": False, "gere_par_repo": None},
            {"gere_par_repo": False},
            {"arbre_repo": False},
        ):
            with self.subTest(**manque):
                l = ligne(regle(**manque), "Engine")
                self.assertEqual(state_screen.A_REGLER, l.etat)
                self.assertIn(self.MV, l.detail)

    def test_an_unknown_management_is_never_carried(self):
        l = ligne(regle(gere_par_repo=None), "Engine")
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertNotIn(self.MV, l.detail)

    def test_only_a_listed_path_where_repo_laid_the_tree_is_managed(self):
        """La règle du script de rapatriement : la liste de Google Repo
        porte le chemin ET repo y a posé l'arbre. Une lecture fausse en
        fait un clone manuel, qui nomme sa mise de côté ; une lecture
        inconnue, sans lecture fausse, ne nomme aucun geste."""
        for liste in (True, False, None):
            for arbre in (True, False, None):
                with self.subTest(gere_par_repo=liste, arbre_repo=arbre):
                    l = ligne(
                        regle(gere_par_repo=liste, arbre_repo=arbre), "Engine"
                    )
                    if liste is True and arbre is True:
                        self.assertEqual(state_screen.PORTE, l.etat)
                        continue
                    self.assertEqual(state_screen.A_REGLER, l.etat)
                    if liste is False or arbre is False:
                        self.assertIn(self.MV, l.detail)
                    else:
                        self.assertNotIn(self.MV, l.detail)

    def test_every_relation_but_equal_is_never_carried(self):
        autres = [r for r in engine.RELATIONS if r != engine.EGAL]
        for relation in autres + ["hors-vocabulaire"]:
            with self.subTest(relation=relation):
                l = ligne(regle(relation=relation, ecart=3), "Engine")
                self.assertEqual(state_screen.A_REGLER, l.etat)

    def test_each_relation_says_its_own_finding(self):
        """Chaque relation a son constat, et lui seul : « en retard » dit de
        resynchroniser, et dit d'un clone en avance, ce geste perdrait ses
        commits locaux. Une épingle absente du clone se rapatrie ; une
        relation inconnue n'établit rien, et ne conseille donc aucun
        geste. Toute relation du vocabulaire clos, hors l'égalité, figure
        dans la table : une relation neuve sans constat rougit ici."""
        attendus = {
            engine.AVANCE: t("{n} commit(s) ahead of the pin").format(n=7),
            engine.RETARD: t(
                "{n} commit(s) behind the pin: resynchronize"
            ).format(n=7),
            engine.DIVERGE: t("HEAD does not descend from the pin"),
            engine.ABSENTE: t(
                "the pin is unknown to this clone: resynchronize"
            ),
            engine.INCONNUE: t(
                "cannot tell where HEAD stands against the pin"
            ),
        }
        self.assertEqual(set(engine.RELATIONS) - {engine.EGAL}, set(attendus))
        cas = dict(attendus)
        cas["hors-vocabulaire"] = attendus[engine.INCONNUE]
        for relation, attendu in cas.items():
            with self.subTest(relation=relation):
                l = ligne(regle(relation=relation, ecart=7), "Engine")
                self.assertIn(attendu, l.detail)
                for autre in set(attendus.values()) - {attendu}:
                    self.assertNotIn(autre, l.detail)

    def test_the_distance_to_the_pin_is_counted(self):
        for relation in (engine.AVANCE, engine.RETARD):
            with self.subTest(relation=relation):
                l = ligne(regle(relation=relation, ecart=7), "Engine")
                self.assertIn("7", l.detail)

    def test_a_dirty_tree_is_never_carried(self):
        for modifies in (1, None):
            with self.subTest(modifies=modifies):
                l = ligne(regle(modifies=modifies), "Engine")
                self.assertEqual(state_screen.A_REGLER, l.etat)

    def test_several_findings_are_all_named(self):
        l = ligne(
            regle(gere_par_repo=False, relation=engine.AVANCE, ecart=2),
            "Engine",
        )
        self.assertIn(self.MV, l.detail)
        self.assertIn("2", l.detail)
        self.assertIn(";", l.detail)

    def test_an_absent_engine_names_the_fetch_script(self):
        vu = regle(chemin_occupe=False, moteur_present=False, arbre_repo=None)
        l = ligne(vu, "Engine")
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertEqual(t("absent: {cmd}").format(cmd=S.RAPATRIER), l.detail)

    def test_an_unpinned_manifest_comes_first(self):
        l = ligne(regle(revision="main"), "Engine")
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertIn("Engine manifest", l.detail)

    def test_the_pin_is_not_judged_when_git_cannot_read_the_clone(self):
        """Un git qui ne lit pas le clone ne dit rien de l'épingle : la
        ligne nomme ce qu'elle sait, et aucun constat d'épingle qu'elle n'a
        pas établi."""
        constats = {S._constat_epingle(r, None) for r in engine.RELATIONS}
        constats.discard("")
        for relation in engine.RELATIONS:
            with self.subTest(relation=relation):
                l = ligne(
                    regle(relation=relation, ecart=None, modifies=None),
                    "Engine",
                )
                self.assertEqual(state_screen.A_REGLER, l.etat)
                self.assertIn(t("git cannot read the engine"), l.detail)
                for constat in constats:
                    self.assertNotIn(constat, l.detail)

    def test_a_readable_clone_still_names_an_unknown_pin(self):
        """Contrôle positif : git lit le clone, l'épingle reste nommée."""
        for relation in (engine.ABSENTE, engine.INCONNUE):
            with self.subTest(relation=relation):
                l = ligne(regle(relation=relation, ecart=None), "Engine")
                constat = S._constat_epingle(relation, None)
                self.assertTrue(constat)
                self.assertIn(constat, l.detail)


class TestAnsible(CasDeLangue):
    def test_a_version_within_the_engine_range_is_carried(self):
        l = ligne(regle(), "Ansible environment")
        self.assertEqual(state_screen.PORTE, l.etat)
        self.assertIn("2.18.6", l.detail)

    def test_a_version_outside_the_range_is_never_carried(self):
        """Les pré-versions « 2.18.1rc1 » et « 2.18.5.dev0 » tombent entre
        les bornes : seule la règle des pré-versions les refuse, et elle ne
        dépend pas de la version de `packaging` installée."""
        for version in (
            "2.19.0",
            "2.17.9",
            "2.18.0rc1",
            "2.18.1rc1",
            "2.18.5.dev0",
        ):
            with self.subTest(version=version):
                l = ligne(
                    regle(version_ansible=version), "Ansible environment"
                )
                self.assertEqual(state_screen.A_REGLER, l.etat)

    def test_a_prerelease_is_carried_when_the_range_names_one(self):
        l = ligne(
            regle(
                plage_ansible="ansible-core>=2.18.0rc1,<2.19",
                version_ansible="2.18.1rc1",
            ),
            "Ansible environment",
        )
        self.assertEqual(state_screen.PORTE, l.etat)

    def test_an_unreadable_range_is_never_carried(self):
        """La plage se LIT dans le moteur : une forme inattendue refuse au
        lieu de deviner, et une plage sans borne n'en est pas une."""
        for plage in (
            None,
            "",
            "pas une exigence !",
            "ansible-core",
            "ansible>=2.18,<2.19",
            "ansible-core[extra]>=2.18,<2.19",
            "ansible-core>=2.18,<2.19; python_version>'3'",
        ):
            with self.subTest(plage=plage):
                l = ligne(regle(plage_ansible=plage), "Ansible environment")
                self.assertEqual(state_screen.ABSENT, l.etat)
                self.assertEqual(
                    t("the engine's ansible-core range is unreadable"),
                    l.detail,
                )

    def test_an_unreadable_version_is_never_carried(self):
        """Le venv est local, et un geste le règle ICI : sa version
        illisible est à régler, et la ligne nomme le venv."""
        for version in (None, "", "banane"):
            with self.subTest(version=version):
                l = ligne(
                    regle(version_ansible=version), "Ansible environment"
                )
                self.assertEqual(state_screen.A_REGLER, l.etat)
                self.assertIn(S.VENV, l.detail)

    def test_a_missing_venv_names_the_gesture_that_sets_it_up(self):
        """« absent » dirait « le dépôt ne sait pas le faire », ce qui a
        cessé d'être vrai : la ligne est à RÉGLER, et elle nomme le geste
        du menu qui la règle."""
        l = ligne(regle(ansible_playbook=False), "Ansible environment")
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertIn(S.VENV, l.detail)
        self.assertIn(t(S.GESTE_ANSIBLE), l.detail)


class TestEcosysteme(CasDeLangue):
    def test_a_mounted_ecosystem_is_carried_and_named(self):
        l = ligne(regle(), "Mounted ecosystem")
        self.assertEqual(state_screen.PORTE, l.etat)
        self.assertIn(ECOSYSTEME, l.detail)

    def test_no_link_names_the_switch(self):
        l = ligne(
            regle(ecosysteme="", plan_present=False), "Mounted ecosystem"
        )
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertIn("instance-utiliser", l.detail)
        self.assertIn(CHEMIN, l.detail)

    def test_a_link_without_plan_is_never_carried(self):
        l = ligne(regle(plan_present=False), "Mounted ecosystem")
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertIn(ECOSYSTEME, l.detail)

    def test_a_real_folder_is_never_carried(self):
        """Le moteur refuse de basculer un vrai dossier : le dire monté
        cacherait le seul geste qui ne marchera pas."""
        l = ligne(
            regle(instance_reelle=True, ecosysteme="", plan_present=True),
            "Mounted ecosystem",
        )
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertNotIn("instance-utiliser", l.detail)


class TestSite(CasDeLangue):
    def test_a_mounted_site_is_carried_and_named(self):
        l = ligne(regle(), "Mounted site")
        self.assertEqual(state_screen.PORTE, l.etat)
        self.assertIn(SITE, l.detail)

    def test_no_site_names_the_link_to_lay(self):
        l = ligne(regle(site=""), "Mounted site")
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertIn("ln -sfn", l.detail)
        self.assertIn(f"{CHEMIN}/underlay.yml", l.detail)

    def test_the_named_link_mounts_the_site_once_replayed(self):
        """Le geste se tape depuis la racine d'ERPLibre, comme tous ceux de
        l'écran, et la cible d'un lien se résout depuis le dossier du LIEN.
        Rejoué tel qu'affiché, un dossier frère à la place du repère qui
        précède `underlay.yml`, il monte ce site-là."""
        l = ligne(regle(site=""), "Mounted site")
        avant, _, apres = t("no site mounted: {cmd}").partition("{cmd}")
        self.assertTrue(l.detail.startswith(avant), l.detail)
        self.assertTrue(l.detail.endswith(apres), l.detail)
        argv = shlex.split(l.detail[len(avant) : len(l.detail) - len(apres)])
        cible = argv[-2].split("/")
        self.assertEqual("underlay.yml", cible[-1], argv)
        cible[-2] = FRERE_REJOUE
        argv[-2] = "/".join(cible)
        with tempfile.TemporaryDirectory() as racine:
            os.makedirs(os.path.join(racine, CHEMIN))
            ecrire(
                os.path.join(
                    racine, "private", "repo", FRERE_REJOUE, "underlay.yml"
                ),
                "{}\n",
            )
            subprocess.run(argv, cwd=racine, check=True)
            self.assertEqual(
                FRERE_REJOUE,
                ecosystems.site_monte(os.path.join(racine, CHEMIN)),
                argv,
            )

    def test_a_link_to_no_file_is_named_as_such(self):
        """Un lien qui ne mène à aucun fichier — brisé, ou vers un dossier —
        ne monte rien, et le moteur le lit comme aucun site ; la ligne dit
        qu'il ne mène à aucun fichier, sans quoi elle redonnerait le même
        geste sans dire pourquoi le précédent n'a rien monté."""
        sans_lien = ligne(regle(site=""), "Mounted site")
        brise = ligne(regle(site="", site_brise=True), "Mounted site")
        self.assertEqual(state_screen.A_REGLER, brise.etat)
        self.assertNotEqual(sans_lien.detail, brise.detail)
        self.assertIn(f"{CHEMIN}/underlay.yml", brise.detail)


class TestLesGestesCitentLeChemin(CasDeLangue):
    """Un geste se recopie tel quel : le chemin déclaré y reste UN argument
    pour le shell, même avec une espace ou une apostrophe, que
    `engine.parse_manifest` accepte. L'épreuve relit la commande comme le
    shell la lit, et non le texte affiché : toute citation juste passe."""

    CHEMIN_A_CITER = "private/repo/Moteur Fictif d'Amphibolite"
    # L'espace et l'apostrophe dans le PARENT : la sonde de l'emplacement
    # ne garde que lui.
    PARENT_A_CITER = (
        "private/Depots d'Essai Fictifs-Tourmaline/Moteur-Fictif-Tourmaline"
    )

    @staticmethod
    def arguments(commande):
        """Les arguments que le shell lit dans `commande` ; [] s'il ne sait
        pas la lire."""
        try:
            return shlex.split(commande)
        except ValueError:
            return []

    def test_every_gesture_keeps_the_path_one_argument(self):
        c = self.CHEMIN_A_CITER
        lien = c + "/underlay.yml"
        cas = (
            (
                "Mounted ecosystem",
                {"ecosysteme": ""},
                "no ecosystem mounted: {cmd}",
                c,
            ),
            ("Mounted site", {"site": ""}, "no site mounted: {cmd}", lien),
            (
                "Mounted site",
                {"site": "", "site_brise": True},
                "underlay.yml leads to no file: {cmd}",
                lien,
            ),
            (
                "Ecosystem vault key",
                {"code_cle": 1},
                "missing: {cmd} names it",
                c + "/scripts/voutes.py",
            ),
        )
        for segment, remplace, gabarit, attendu in cas:
            with self.subTest(segment=segment, gabarit=gabarit):
                detail = ligne(regle(chemin=c, **remplace), segment).detail
                avant, _, apres = t(gabarit).partition("{cmd}")
                self.assertTrue(detail.startswith(avant), detail)
                self.assertTrue(detail.endswith(apres), detail)
                commande = detail[len(avant) : len(detail) - len(apres)]
                self.assertIn(attendu, self.arguments(commande), commande)

    def test_the_location_source_names_the_probe_as_one_argument(self):
        c = self.PARENT_A_CITER
        source = ligne(regle(chemin=c), "Private location").source
        self.assertEqual(
            [engine.ignore_probe(c)], self.arguments(source)[-1:], source
        )


class TestCleDeVoute(CasDeLangue):
    def test_only_code_zero_is_carried(self):
        attendu = {
            0: state_screen.PORTE,
            1: state_screen.A_REGLER,
            2: state_screen.A_REGLER,
            None: state_screen.A_REGLER,
        }
        for code, etat in attendu.items():
            with self.subTest(code=code):
                l = ligne(regle(code_cle=code), "Ecosystem vault key")
                self.assertEqual(etat, l.etat)

    def test_a_missing_key_names_the_command_that_names_it(self):
        l = ligne(regle(code_cle=1), "Ecosystem vault key")
        self.assertIn(f"{CHEMIN}/scripts/voutes.py etat", l.detail)

    def test_an_unexpected_code_is_an_unreadable_verdict(self):
        """Une sonde qui n'a pas répondu ne dit pas la clé absente."""
        for code in (2, -9, None):
            with self.subTest(code=code):
                l = ligne(regle(code_cle=code), "Ecosystem vault key")
                self.assertEqual(
                    t("unreadable verdict (code {code})").format(
                        code="?" if code is None else code
                    ),
                    l.detail,
                )


class TestPrealables(CasDeLangue):
    """Préalable non tenu : la ligne prend ◐ et le NOMME, sans autre
    verdict — un verdict rendu sur un moteur absent ne décrirait rien."""

    def test_an_absent_engine_is_named_by_lines_six_to_eight(self):
        vu = regle(moteur_present=False)
        for segment in ("Ansible environment", "Mounted ecosystem"):
            with self.subTest(segment=segment):
                l = ligne(vu, segment)
                self.assertEqual(state_screen.A_REGLER, l.etat)
                self.assertIn("Engine", l.detail)
        l = ligne(vu, "Mounted site")
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertIn("Engine", l.detail)

    def test_the_key_waits_for_the_mounted_ecosystem(self):
        """`voutes.py etat` rend 0 quand il n'a rien à nommer : sans
        écosystème monté, son code ne prouve rien."""
        vu = regle(moteur_present=False)
        l = ligne(vu, "Ecosystem vault key")
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertIn("Mounted ecosystem", l.detail)
        l = ligne(regle(ecosysteme="", code_cle=0), "Ecosystem vault key")
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertIn("Mounted ecosystem", l.detail)

    def test_a_manual_clone_hides_none_of_the_lines_next_to_it(self):
        """Le préalable des lignes 6, 7 et 8 est « moteur PRÉSENT », pas
        « ligne 5 portée » : un clone manuel laisse la ligne 5 à régler, et
        l'environnement, l'écosystème et le site réglés à côté de lui n'en
        sont pas moins réglés. Les trois segments sont écrits ici, et non
        tirés de `PREALABLES` : la table éprouvée ne choisit pas ses
        épreuves."""
        vu = regle(repo_initialise=False, gere_par_repo=None)
        self.assertEqual(state_screen.A_REGLER, ligne(vu, "Engine").etat)
        d_abord = t("first: {segment}").partition("{segment}")[0]
        for segment in (
            "Ansible environment",
            "Mounted ecosystem",
            "Mounted site",
        ):
            with self.subTest(segment=segment):
                l = ligne(vu, segment)
                self.assertEqual(state_screen.PORTE, l.etat)
                self.assertNotIn(d_abord, l.detail)

    def test_an_unmet_prerequisite_hides_the_line_own_verdict(self):
        """Un venv absent serait ○ ; sans moteur, la ligne dit d'abord
        le moteur, et rien d'autre."""
        l = ligne(
            regle(moteur_present=False, ansible_playbook=False),
            "Ansible environment",
        )
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertNotIn(S.VENV, l.detail)


class TestPrealablesTraduits(CasDeLangue):
    LANGUE = "fr"

    def test_the_prerequisite_is_named_in_the_language(self):
        vu = regle(moteur_present=False)
        for segment in (
            "Ansible environment",
            "Mounted ecosystem",
            "Mounted site",
        ):
            with self.subTest(segment=segment):
                self.assertIn("Moteur", ligne(vu, segment).detail)
        self.assertIn(
            "Écosystème monté", ligne(vu, "Ecosystem vault key").detail
        )


class TestConstatsJointsDansLaLangue(unittest.TestCase):
    """Plusieurs constats d'une ligne se joignent selon la typographie de
    la langue : une espace avant le point-virgule en français, aucune en
    anglais. Collé au dernier mot, il se lit comme la fin d'une commande."""

    # Au moins deux constats sur chacune des trois lignes qui en joignent.
    VU = dict(
        outil_repo=False,
        repo_initialise=False,
        gere_par_repo=False,
        relation=engine.RETARD,
        ecart=3,
        modifies=2,
        outils_absents=("make", "gpg"),
    )
    ACCOLE = {"fr": r"\S;", "en": r" ;"}

    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )

    def test_findings_are_joined_by_the_language_separator(self):
        for langue, motif in self.ACCOLE.items():
            todo_i18n._current_lang = langue
            joints = [l for l in S.lignes(regle(**self.VU)) if ";" in l.detail]
            self.assertLessEqual(
                {t(s) for s in (S.GOOGLE_REPO, S.MOTEUR, S.OUTILS)},
                {l.segment for l in joints},
            )
            for l in joints:
                with self.subTest(langue=langue, segment=l.segment):
                    self.assertIsNone(re.search(motif, l.detail), l.detail)


class TestOutilsDuPoste(CasDeLangue):
    def test_a_missing_core_tool_is_to_set_up_and_named(self):
        for outil in S.OUTILS_COEUR:
            with self.subTest(outil=outil):
                l = ligne(regle(outils_absents=(outil,)), "Station tools")
                self.assertEqual(state_screen.A_REGLER, l.etat)
                self.assertIn(outil, l.detail)

    def test_a_missing_gesture_tool_is_carried_with_a_note(self):
        """L'outil d'un geste particulier ne bloque que ce geste : la
        ligne reste portée, et la note dit ce qu'il bloque."""
        for outil, gestes in S.OUTILS_GESTES:
            with self.subTest(outil=outil):
                l = ligne(regle(outils_absents=(outil,)), "Station tools")
                self.assertEqual(state_screen.PORTE, l.etat)
                self.assertIn(outil, l.detail)
                self.assertIn(gestes, l.detail)

    def test_every_gesture_tool_missing_is_still_carried_and_all_named(self):
        """Le cœur présent suffit, quel que soit le nombre d'outils de
        geste absents : la note les nomme TOUS, chacun avec ce qu'il
        bloque."""
        tous = tuple(o for o, _ in S.OUTILS_GESTES)
        for absents in (("rsync", "dig"), tous):
            l = ligne(regle(outils_absents=absents), "Station tools")
            self.assertEqual(state_screen.PORTE, l.etat)
            for outil, gestes in S.OUTILS_GESTES:
                if outil in absents:
                    with self.subTest(absents=absents, outil=outil):
                        self.assertIn(f"{outil} ({gestes})", l.detail)

    def test_the_blocked_gestures_are_named(self):
        gestes = dict(S.OUTILS_GESTES)
        self.assertIn("depot-hors-site", gestes["rsync"])
        self.assertIn("dnssec-", gestes["dig"])
        self.assertEqual({"make", "git", "ssh"}, set(S.OUTILS_COEUR))


def au_moteur_epingle(chemin):
    """Le texte de `chemin` dans le moteur déclaré, À L'ÉPINGLE, ou None.

    Lu par `git show <épingle>:<chemin>` : c'est la révision que le
    manifeste déclare, et non l'arbre de travail du clone. None sans clone
    qui connaisse l'épingle ; la recherche du dépôt s'arrête au clone, et
    ne répond donc jamais pour ERPLibre.
    """
    decl = engine.declaration(RACINE_DEPOT)
    if decl is None or not engine.is_pinned(decl.revision):
        return None
    moteur = os.path.realpath(os.path.join(RACINE_DEPOT, decl.path))
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CEILING_DIRECTORIES"] = os.path.dirname(moteur)
    try:
        fait = subprocess.run(
            ["git", "-C", moteur, "show", f"{decl.revision}:{chemin}"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return fait.stdout if fait.returncode == 0 else None


class TestLeMoteurEpingleConnaitCeQueLEcranNomme(unittest.TestCase):
    """Les cibles et le document que l'écran nomme existent dans le moteur
    épinglé : un nom qui n'y est pas envoie chercher un geste introuvable.

    Seule épreuve de ce fichier à lire le vrai moteur, et seulement là où
    un clone connaît l'épingle ; ailleurs — en CI, `private/repo/` est
    ignoré par git — elle se dit ignorée.
    """

    @classmethod
    def setUpClass(cls):
        cls.makefile = au_moteur_epingle("Makefile")
        if cls.makefile is None:
            raise unittest.SkipTest("aucun clone ne connaît l'épingle")

    def test_every_blocked_gesture_is_a_target_of_the_engine(self):
        cibles = set(
            re.findall(r"^([A-Za-z0-9_.-]+)[ \t]*:(?!=)", self.makefile, re.M)
        )
        self.assertTrue(cibles)
        for outil, gestes in S.OUTILS_GESTES:
            for geste in gestes.split(", "):
                with self.subTest(outil=outil, geste=geste):
                    self.assertTrue(fnmatch.filter(cibles, geste))

    def test_the_site_document_exists_in_the_engine(self):
        self.assertIsNotNone(au_moteur_epingle(S.DOC_SITE))


class TestInconnuJamaisPorte(CasDeLangue):
    """Fermé par défaut : un verdict inconnu ne se lit jamais « porté »."""

    CHAMPS = {
        "parent_ignore": "Private location",
        "gere_par_repo": "Engine",
        "arbre_repo": "Engine",
        "modifies": "Engine",
        "version_ansible": "Ansible environment",
        "plage_ansible": "Ansible environment",
        "mineur_path": "Ansible environment",
        "biblios_epinglees": "Ansible environment",
        "collections_epinglees": "Ansible environment",
        "code_cle": "Ecosystem vault key",
    }

    def test_every_unknown_verdict_is_never_carried(self):
        for champ, segment in self.CHAMPS.items():
            with self.subTest(champ=champ):
                l = ligne(regle(**{champ: None}), segment)
                self.assertNotEqual(state_screen.PORTE, l.etat)

    def test_every_field_that_can_be_unknown_is_covered(self):
        """Un champ neuf qui peut valoir None doit entrer dans la table
        ci-dessus, faute de quoi son inconnu passerait sans épreuve."""
        vu = vide()
        peuvent = {c for c in S.Releve._fields if getattr(vu, c) is None} - {
            "ecart"
        }
        self.assertEqual(set(self.CHAMPS), peuvent)

    def test_a_station_where_nothing_is_readable_carries_no_line(self):
        self.assertNotIn(
            state_screen.PORTE, [l.etat for l in S.lignes(vide())]
        )

    def test_each_unknown_alone_keeps_a_line_from_being_carried(self):
        """L'inconnu d'un champ n'est pas toujours None : une plateforme
        que le système ne nomme pas vaut "". Chaque champ pris dans le
        relevé illisible, seul dans un relevé réglé, retire au moins une
        ligne du compte porté. `ecart` ne fait que qualifier une relation."""
        illisible, porte = vide(), regle()
        for champ in S.Releve._fields:
            valeur = getattr(illisible, champ)
            if champ == "ecart" or valeur == getattr(porte, champ):
                continue
            with self.subTest(champ=champ):
                etats = [l.etat for l in S.lignes(regle(**{champ: valeur}))]
                self.assertNotEqual([state_screen.PORTE] * 10, etats)


class TestLaDecisionNeLitPasLaMachine(CasDeLangue):
    """`lignes` est PURE : c'est ce qui permet d'éprouver l'état d'un
    poste qu'on n'a pas sous la main."""

    def test_lines_are_decided_with_every_probe_forbidden(self):
        interdit = mock.Mock(side_effect=AssertionError("E/S dans lignes"))
        with (
            mock.patch("builtins.open", interdit),
            mock.patch("subprocess.run", interdit),
            mock.patch("subprocess.Popen", interdit),
            mock.patch("shutil.which", interdit),
            mock.patch("platform.system", interdit),
            mock.patch("os.path.exists", interdit),
            mock.patch("os.path.lexists", interdit),
            mock.patch("os.path.isdir", interdit),
            mock.patch("os.path.isfile", interdit),
            mock.patch("os.path.islink", interdit),
            mock.patch("os.stat", interdit),
        ):
            for vu in (regle(), vide()):
                self.assertEqual(10, len(S.lignes(vu)))
        interdit.assert_not_called()


# Le nom qu'imprime le faux `voutes.py` : la sortie du vrai nomme
# l'écosystème, et rien de ce qu'il imprime ne doit être conservé.
NOM_IMPRIME = "Voute-Fictive-Jaspe"
FUITE = "FUITE_FICTIVE_ORTHOSE"

# Un module posé à côté du faux `voutes.py`, qu'il importe comme le vrai
# importe les siens : c'est ce qui ferait écrire un `__pycache__`.
VOISIN = "voisin_fictif_andesite"

FAUX_VOUTES = """\
import json, os, sys, time
from pathlib import Path

import {voisin}

trace = Path(__file__).resolve().parents[2] / "trace-voutes.json"
trace.write_text(json.dumps({{
    "cwd": os.getcwd(),
    "env": sorted(os.environ),
    "argv": sys.argv[1:],
}}))
print("cle presente {nom}")
print("CLE ABSENTE {nom}", file=sys.stderr)
time.sleep({attente})
sys.exit({code})
"""

DEFAUTS = 'serveur_ops_ansible: "ansible-core>=2.18,<2.19"\n'


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


def ecrire(chemin, texte, mode=None):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(texte)
    if mode is not None:
        os.chmod(chemin, mode)


class CasDePoste(CasDeLangue):
    """Un faux poste ENTIÈREMENT réglé, dans un dossier temporaire.

    La racine est un dépôt git qui ignore `private/repo/` ; le moteur, un
    dépôt git épinglé par le manifeste et posé comme Google Repo le pose :
    listé dans `.repo/project.list`, son dépôt sous `.repo/projects/` et
    son `.git` un lien qui y mène. Un écosystème et un site montés par
    liens ; un venv dont le Python imprime une version. Chaque épreuve
    défait ce qu'elle éprouve.
    """

    def setUp(self):
        super().setUp()
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine, True)
        r = self.racine
        git(r, "init", "-q")
        ecrire(os.path.join(r, ".gitignore"), "private/repo/\n")
        git(r, "add", ".gitignore")
        git(r, "commit", "-q", "-m", "racine")

        self.depots = os.path.join(r, "private", "repo")
        self.moteur = os.path.join(r, CHEMIN)
        m = self.moteur
        self.voutes(0)
        ecrire(os.path.join(m, ansible_env.DEFAULTS_ANSIBLE), DEFAUTS)
        # Le moteur déclare ses épingles, et n'en porte aucune : la ligne
        # dit alors « 0 bibliothèques et 0 collections à l'épingle », ce qui
        # est un état réel. Les épingles elles-mêmes s'éprouvent à côté,
        # sur la couche qui les lit.
        ecrire(os.path.join(m, ansible_env.REQUIREMENTS_PY), "# aucune\n")
        ecrire(
            os.path.join(m, ansible_env.REQUIREMENTS_YML), "collections: []\n"
        )
        ecrire(os.path.join(m, ".gitignore"), "instance\nunderlay.yml\n")
        git(m, "init", "-q")
        git(m, "add", "-A")
        git(m, "commit", "-q", "-m", "moteur")
        sha = git(m, "rev-parse", "HEAD")
        self.depot_git = os.path.join(r, ".repo", "projects", CHEMIN + ".git")
        os.makedirs(os.path.dirname(self.depot_git))
        shutil.move(os.path.join(m, ".git"), self.depot_git)
        os.symlink(os.path.relpath(self.depot_git, m), os.path.join(m, ".git"))

        ecrire(
            os.path.join(self.depots, ECOSYSTEME, "plan", "serveurs.yml"),
            "{}\n",
        )
        os.symlink(os.path.join("..", ECOSYSTEME), os.path.join(m, "instance"))
        ecrire(os.path.join(self.depots, SITE, "underlay.yml"), "{}\n")
        os.symlink(
            os.path.join("..", SITE, "underlay.yml"),
            os.path.join(m, "underlay.yml"),
        )

        ecrire(
            os.path.join(r, engine.MANIFEST),
            '<?xml version="1.0" encoding="UTF-8" ?>\n<manifest>\n'
            '  <project name="Moteur-Fictif-Granit.git"'
            f' path="{CHEMIN}" revision="{sha}" groups="setops" />\n'
            "</manifest>\n",
        )
        ecrire(os.path.join(r, ".repo", "project.list"), CHEMIN + "\n")
        ecrire(os.path.join(r, ".repo", "manifest.xml"), "<manifest />\n")
        ecrire(os.path.join(r, S.OUTIL_REPO), "#!/bin/sh\n", 0o755)
        self.venv = os.path.join(r, S.VENV)
        ecrire(
            os.path.join(self.venv, "bin", "ansible-playbook"),
            "#!/bin/sh\n",
            0o755,
        )
        self.python_du_venv("echo 2.18.6")
        # `python3` du PATH du geste : la sonde du mineur passe par lui,
        # et c'est le venv qui doit répondre, pas l'interpréteur du poste.
        self.python3_du_venv(ansible_env.MINEUR_CIBLE)

    def python3_du_venv(self, mineur):
        ecrire(
            os.path.join(self.venv, "bin", "python3"),
            f"#!/bin/sh\necho {mineur}\n",
            0o755,
        )

    def cloner_a_la_main(self):
        """Rend au moteur un vrai dossier `.git` : un clone manuel, au
        chemin que la liste de Google Repo porte toujours."""
        dotgit = os.path.join(self.moteur, ".git")
        os.remove(dotgit)
        shutil.move(self.depot_git, dotgit)

    def voutes(self, code, attente=0):
        scripts = os.path.join(self.moteur, "scripts")
        ecrire(os.path.join(scripts, VOISIN + ".py"), "VALEUR = 1\n")
        ecrire(
            os.path.join(scripts, "voutes.py"),
            FAUX_VOUTES.format(
                nom=NOM_IMPRIME, code=code, attente=attente, voisin=VOISIN
            ),
        )

    def python_du_venv(self, corps):
        ecrire(
            os.path.join(self.venv, "bin", "python"),
            "#!/bin/sh\n" + corps + "\n",
            0o755,
        )

    def trace(self):
        chemin = os.path.join(self.depots, "trace-voutes.json")
        if not os.path.exists(chemin):
            return None
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)

    def vu(self):
        """Le relevé du faux poste, outils et plateforme posés."""
        with (
            mock.patch.object(
                S.shutil, "which", return_value="/chemin/fictif"
            ),
            mock.patch.object(S.platform, "system", return_value="Linux"),
        ):
            return S.releve(self.racine)


class TestLeReleveDUnPosteRegle(CasDePoste):
    def test_a_settled_station_carries_all_ten(self):
        """Le contrôle positif de bout en bout : relevé ET décision."""
        vu = self.vu()
        self.assertEqual(
            [state_screen.PORTE] * 10,
            [l.etat for l in S.lignes(vu)],
            S.lignes(vu),
        )

    def test_what_the_survey_reads(self):
        vu = self.vu()
        self.assertEqual(CHEMIN, vu.chemin)
        self.assertIs(True, vu.parent_ignore)
        self.assertIs(True, vu.gere_par_repo)
        self.assertIs(True, vu.arbre_repo)
        self.assertEqual(
            (engine.EGAL, 0, 0), (vu.relation, vu.ecart, vu.modifies)
        )
        self.assertEqual("2.18.6", vu.version_ansible)
        self.assertEqual(PLAGE, vu.plage_ansible)
        self.assertEqual(
            (False, ECOSYSTEME, True),
            (vu.instance_reelle, vu.ecosysteme, vu.plan_present),
        )
        self.assertEqual(SITE, vu.site)
        self.assertEqual(0, vu.code_cle)


class TestLeReleveRefleteLePoste(CasDePoste):
    """Le relevé suit le poste dans les DEUX sens. Le poste réglé montre
    le sens porté ; chaque épreuve ici désajuste UN point, et le champ comme
    la ligne doivent le voir. Une sonde remplacée par sa « bonne » valeur
    passerait le poste réglé, et porterait ce qu'il faudrait refuser."""

    def test_the_platform_is_asked_to_the_system(self):
        with (
            mock.patch.object(
                S.shutil, "which", return_value="/chemin/fictif"
            ),
            mock.patch.object(
                S.platform, "system", return_value="Systeme-Fictif-Dunite"
            ),
        ):
            vu = S.releve(self.racine)
        self.assertEqual("Systeme-Fictif-Dunite", vu.systeme)
        self.assertEqual(state_screen.ABSENT, ligne(vu, "Platform").etat)

    def test_a_parent_git_does_not_ignore_is_seen(self):
        ecrire(os.path.join(self.racine, ".gitignore"), "autre/\n")
        vu = self.vu()
        self.assertIs(False, vu.parent_ignore)
        l = ligne(vu, "Private location")
        self.assertEqual(state_screen.ABSENT, l.etat)
        self.assertIn("NOT ignored", l.detail)

    def test_a_project_list_that_ignores_the_engine_is_seen(self):
        ecrire(
            os.path.join(self.racine, ".repo", "project.list"), "ailleurs\n"
        )
        vu = self.vu()
        self.assertEqual((True, False), (vu.repo_initialise, vu.gere_par_repo))
        l = ligne(vu, "Engine")
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertIn(engine.mise_de_cote(CHEMIN), l.detail)

    def test_a_commit_past_the_pin_is_seen(self):
        git(self.moteur, "commit", "-q", "--allow-empty", "-m", "au-dela")
        vu = self.vu()
        self.assertEqual((engine.AVANCE, 1), (vu.relation, vu.ecart))
        self.assertEqual(state_screen.A_REGLER, ligne(vu, "Engine").etat)

    def test_a_missing_repo_tool_is_seen(self):
        os.remove(os.path.join(self.racine, S.OUTIL_REPO))
        vu = self.vu()
        self.assertIs(False, vu.outil_repo)
        l = ligne(vu, "Google Repo")
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertIn(S.INSTALLER_REPO, l.detail)


class TestLeReleveDuMoteur(CasDePoste):
    def test_a_manual_clone_is_seen_and_hides_none_of_its_neighbours(self):
        self.cloner_a_la_main()
        shutil.rmtree(os.path.join(self.racine, ".repo"))
        vu = self.vu()
        self.assertFalse(vu.repo_initialise)
        moteur = ligne(vu, "Engine")
        self.assertEqual(state_screen.A_REGLER, moteur.etat)
        self.assertIn(f"mv {CHEMIN} {CHEMIN}.manuel", moteur.detail)
        for segment in (
            "Ansible environment",
            "Mounted ecosystem",
            "Mounted site",
        ):
            with self.subTest(segment=segment):
                self.assertEqual(state_screen.PORTE, ligne(vu, segment).etat)

    def test_without_declaration_no_engine_is_read(self):
        os.remove(os.path.join(self.racine, engine.MANIFEST))
        vu = self.vu()
        self.assertEqual(
            ("", False, None), (vu.chemin, vu.moteur_present, vu.code_cle)
        )
        self.assertIsNone(self.trace())

    def test_a_pin_the_clone_never_fetched_names_the_resynchronization(self):
        """Le manifeste épingle un commit que le clone n'a jamais reçu : git
        lit le clone, l'épingle y manque, et la ligne dit de resynchroniser
        au lieu de dire qu'elle ne sait pas."""
        chemin = os.path.join(self.racine, engine.MANIFEST)
        with open(chemin, encoding="utf-8") as f:
            texte = f.read()
        ecrire(
            chemin,
            re.sub(r'revision="[0-9a-f]{40}"', f'revision="{SHA}"', texte),
        )
        vu = self.vu()
        self.assertEqual((SHA, engine.ABSENTE), (vu.revision, vu.relation))
        l = ligne(vu, "Engine")
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertIn(
            t("the pin is unknown to this clone: resynchronize"), l.detail
        )
        self.assertNotIn(
            t("cannot tell where HEAD stands against the pin"), l.detail
        )

    def test_an_untracked_file_dirties_the_engine(self):
        ecrire(os.path.join(self.moteur, "ajout"), "x")
        self.assertEqual(1, self.vu().modifies)

    def test_a_folder_git_cannot_read_names_no_pin_finding(self):
        """Un dossier qui n'est pas un dépôt, au chemin déclaré : git ne
        répond pas, et la ligne ne prête au clone aucune épingle. Le chemin
        reste listé, et repo n'y a rien posé : la ligne nomme la mise de
        côté que le script de rapatriement exige."""
        os.remove(os.path.join(self.moteur, ".git"))
        l = ligne(self.vu(), "Engine")
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertIn(t("git cannot read the engine"), l.detail)
        self.assertIn(engine.mise_de_cote(CHEMIN), l.detail)
        for relation in engine.RELATIONS:
            constat = S._constat_epingle(relation, None)
            if constat:
                self.assertNotIn(constat, l.detail)


class TestLeReleveDeGoogleRepo(CasDePoste):
    def test_a_repo_folder_left_by_a_merge_alone_is_not_initialized(self):
        """La fusion des manifestes crée `.repo/local_manifests/` sans
        `repo init` : ce dossier-là n'est pas un espace initialisé, et la
        ligne nomme le geste qui l'initialise."""
        shutil.rmtree(os.path.join(self.racine, ".repo"))
        ecrire(
            os.path.join(
                self.racine, ".repo", "local_manifests", "fusion-fictive.xml"
            ),
            "<manifest />\n",
        )
        l = ligne(self.vu(), "Google Repo")
        self.assertNotEqual(state_screen.PORTE, l.etat)
        self.assertIn(S.RAPATRIER, l.detail)

    def test_repo_init_marks_the_workspace_initialized(self):
        """Contrôle positif : le manifeste qu'écrit `repo init` suffit."""
        shutil.rmtree(os.path.join(self.racine, ".repo"))
        ecrire(
            os.path.join(self.racine, ".repo", "manifest.xml"),
            "<manifest />\n",
        )
        l = ligne(self.vu(), "Google Repo")
        self.assertEqual(state_screen.PORTE, l.etat)

    def test_a_repo_tool_that_cannot_run_is_not_counted(self):
        """Le script de rapatriement refuse un `repo` non exécutable :
        l'écran le juge de même."""
        os.chmod(os.path.join(self.racine, S.OUTIL_REPO), 0o644)
        vu = self.vu()
        self.assertEqual(state_screen.A_REGLER, ligne(vu, "Google Repo").etat)
        self.assertFalse(vu.outil_repo)


class TestLEcranEtLeScriptJugentLeCheminPareil(CasDePoste):
    """La ligne du moteur et le script de rapatriement jugent le MÊME
    occupant du chemin déclaré — dossier, fichier ou lien : l'écran ne
    porte que ce que `verifier-emplacement` laisse passer, et nomme la mise
    de côté de tout ce que Google Repo n'a pas posé. Une lecture illisible
    fait exception : le script refuse, et l'écran, qui ne porte pas la
    ligne, ne nomme aucun geste sur un inconnu. Chaque épreuve pose un état
    du chemin, sur le poste réglé, et confronte les deux verdicts."""

    def verdicts(self):
        """(ligne du moteur, code de `verifier-emplacement`, son erreur)."""
        err = io.StringIO()
        code = engine.main(
            ["verifier-emplacement"],
            racine=self.racine,
            out=io.StringIO(),
            err=err,
        )
        return ligne(self.vu(), "Engine"), code, err.getvalue()

    def assertMemeVerdict(self, passe):
        """Les deux sorties disent ensemble si le chemin passe (`passe`) ;
        un refus du script est un `mv` que la ligne nomme aussi."""
        l, code, err = self.verdicts()
        self.assertEqual(
            (passe, passe),
            (l.etat == state_screen.PORTE, code == engine.RC_OK),
            (l, code, err),
        )
        if not passe:
            self.assertEqual(engine.RC_OCCUPE, code, err)
            self.assertIn(engine.mise_de_cote(CHEMIN), l.detail)

    def test_a_tree_linked_under_repo_projects_passes_both(self):
        """Contrôle positif : un écran qui refuserait tout rougit ici."""
        self.assertMemeVerdict(passe=True)

    def test_a_gitdir_file_under_repo_passes_both(self):
        """L'autre forme que pose Google Repo : un fichier « gitdir: »."""
        dotgit = os.path.join(self.moteur, ".git")
        os.remove(dotgit)
        ecrire(
            dotgit,
            "gitdir: " + os.path.relpath(self.depot_git, self.moteur) + "\n",
        )
        self.assertMemeVerdict(passe=True)

    def test_a_real_git_at_a_listed_path_is_refused_by_both(self):
        """Google Repo écrit sa liste même quand le rapatriement échoue :
        un clone manuel, à l'épingle et propre, occupe un chemin listé."""
        self.cloner_a_la_main()
        self.assertMemeVerdict(passe=False)

    def test_a_listed_folder_without_git_is_refused_by_both(self):
        os.remove(os.path.join(self.moteur, ".git"))
        self.assertMemeVerdict(passe=False)

    def test_a_path_the_list_lacks_is_refused_by_both(self):
        ecrire(
            os.path.join(self.racine, ".repo", "project.list"),
            "private/repo/Autre-Fictif-Leucite\n",
        )
        self.assertMemeVerdict(passe=False)

    # Les états du chemin que le balayage pose, chacun sur un poste réglé
    # neuf. Chaque méthode prend le cas et défait ce qu'elle éprouve.
    def _sans_manifeste_de_repo(self):
        os.remove(os.path.join(self.racine, S.MANIFESTE_REPO))

    def _lien_brise_au_chemin(self):
        shutil.rmtree(self.moteur)
        os.symlink("cible-absente-fictive-jaspe", self.moteur)

    def _fichier_au_chemin(self):
        shutil.rmtree(self.moteur)
        ecrire(self.moteur, "fichier-fictif-jaspe\n")

    def _dossier_illisible(self):
        if os.geteuid() == 0:
            self.skipTest("root lit un dossier sans droits")
        os.chmod(self.moteur, 0)
        self.addCleanup(os.chmod, self.moteur, 0o755)

    def _gitdir_hors_de_repo_absent(self):
        dotgit = os.path.join(self.moteur, ".git")
        os.remove(dotgit)
        ecrire(
            dotgit,
            "gitdir: " + os.path.relpath(self.depot_git, self.moteur) + "\n",
        )
        shutil.rmtree(os.path.join(self.racine, ".repo"))

    def _gitdir_illisible(self):
        dotgit = os.path.join(self.moteur, ".git")
        os.remove(dotgit)
        with open(dotgit, "wb") as f:
            f.write(b"gitdir: \xff\xfe\n")

    def test_every_state_of_the_path_gets_one_verdict_from_both(self):
        """Balayage de bout en bout : sur chaque état du chemin, la ligne
        du moteur est portée si et seulement si `verifier-emplacement`
        laisse passer. Un refus du script est un `mv` que la ligne du
        moteur nomme aussi, et la ligne Google Repo est portée ou le nomme
        à son tour ; un passage n'en fait nommer aucun. Une lecture
        illisible (None) ne prouve rien : les deux refusent, et l'écran ne
        nomme aucun geste sur un inconnu."""
        cas = (
            (
                "posé par repo, .repo/manifest.xml absent",
                True,
                (self._sans_manifeste_de_repo,),
            ),
            ("lien brisé au chemin", False, (self._lien_brise_au_chemin,)),
            ("fichier au chemin", False, (self._fichier_au_chemin,)),
            ("dossier illisible au chemin", False, (self._dossier_illisible,)),
            (
                "lien brisé, .repo/ non initialisé",
                False,
                (
                    self._lien_brise_au_chemin,
                    self._sans_manifeste_de_repo,
                ),
            ),
            (
                "fichier, .repo/ non initialisé",
                False,
                (
                    self._fichier_au_chemin,
                    self._sans_manifeste_de_repo,
                ),
            ),
            (
                "clone manuel, .repo/ non initialisé",
                False,
                (
                    self.cloner_a_la_main,
                    self._sans_manifeste_de_repo,
                ),
            ),
            (
                ".repo/ absent, gitdir qui y mènerait",
                False,
                (self._gitdir_hors_de_repo_absent,),
            ),
            (
                "gitdir illisible, chemin listé",
                None,
                (self._gitdir_illisible,),
            ),
        )
        mv = engine.mise_de_cote(CHEMIN)
        for nom, passe, poser in cas:
            with self.subTest(etat=nom):
                self.setUp()  # un poste réglé neuf par état
                for geste in poser:
                    geste()
                err = io.StringIO()
                code = engine.main(
                    ["verifier-emplacement"],
                    racine=self.racine,
                    out=io.StringIO(),
                    err=err,
                )
                vu = self.vu()
                moteur, depot = ligne(vu, "Engine"), ligne(vu, "Google Repo")
                temoin = (moteur, depot, code, err.getvalue())
                if passe is None:
                    self.assertNotEqual(
                        state_screen.PORTE, moteur.etat, temoin
                    )
                    self.assertEqual(engine.RC_OCCUPE, code, temoin)
                    continue
                self.assertEqual(
                    (passe, passe),
                    (moteur.etat == state_screen.PORTE, code == engine.RC_OK),
                    temoin,
                )
                if passe:
                    self.assertNotIn(mv, moteur.detail + depot.detail, temoin)
                    continue
                self.assertEqual(engine.RC_OCCUPE, code, temoin)
                self.assertIn(mv, moteur.detail, temoin)
                self.assertTrue(
                    depot.etat == state_screen.PORTE or mv in depot.detail,
                    temoin,
                )


class TestLaSourceDeLEmplacementSeRejoue(CasDeLangue):
    """La source de la ligne « Emplacement privé », rejouée telle quelle
    depuis la racine, rend le verdict de l'écran.

    Le piège : un fichier SUIVI sous le parent ignoré — un `.gitkeep` —
    rend le parent suivi, et `git check-ignore <parent>` répond « non
    ignoré » là où un frère posé à côté du moteur l'est bel et bien.
    """

    CHEMIN_REJOUE = "depots-fictifs/Moteur-Fictif-Rhyolite"

    def rejoue(self, regles):
        racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, racine, True)
        git(racine, "init", "-q")
        ecrire(os.path.join(racine, ".gitignore"), regles)
        ecrire(os.path.join(racine, "depots-fictifs", ".gitkeep"), "")
        git(racine, "add", "-f", ".gitignore", "depots-fictifs/.gitkeep")
        git(racine, "commit", "-q", "-m", "racine")
        vu = regle(
            chemin=self.CHEMIN_REJOUE,
            parent_ignore=engine.parent_is_ignored(racine, self.CHEMIN_REJOUE),
        )
        l = ligne(vu, "Private location")
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        fait = subprocess.run(
            shlex.split(l.source),
            cwd=racine,
            env=env,
            capture_output=True,
            check=False,
        )
        return l, fait.returncode

    def test_an_ignored_parent_replays_as_ignored(self):
        l, code = self.rejoue("depots-fictifs/\n")
        self.assertEqual((state_screen.PORTE, 0), (l.etat, code), l.source)

    def test_a_parent_not_ignored_replays_as_not_ignored(self):
        l, code = self.rejoue("autre/\n")
        self.assertEqual((state_screen.ABSENT, 1), (l.etat, code), l.source)

    def test_the_source_names_the_path_the_verdict_asks_git_about(self):
        """Le rejeu ci-dessus ne voit pas une source qui sonderait un AUTRE
        nom sous le même parent ignoré : les deux répondent « ignoré ». Ici,
        le chemin que cite la source est celui que `parent_is_ignored`
        soumet à git, pour un moteur avec ou sans parent."""
        questions = []

        def git_espion(racine, *args):
            questions.append(args[-1])
            return None

        for chemin in (self.CHEMIN_REJOUE, "Moteur-Fictif-Rhyolite"):
            with self.subTest(chemin=chemin):
                questions.clear()
                with mock.patch.object(engine, "_git", git_espion):
                    engine.parent_is_ignored("/racine-fictive", chemin)
                source = ligne(regle(chemin=chemin), "Private location").source
                self.assertEqual(questions, shlex.split(source)[-1:])


class TestLeReleveDesLiens(CasDePoste):
    def test_a_real_instance_folder_is_not_a_link(self):
        os.remove(os.path.join(self.moteur, "instance"))
        os.makedirs(os.path.join(self.moteur, "instance", "plan"))
        vu = self.vu()
        self.assertEqual((True, ""), (vu.instance_reelle, vu.ecosysteme))

    def test_a_link_without_plan_is_named(self):
        os.remove(
            os.path.join(self.depots, ECOSYSTEME, "plan", "serveurs.yml")
        )
        vu = self.vu()
        self.assertEqual((ECOSYSTEME, False), (vu.ecosysteme, vu.plan_present))

    def test_no_instance_link_mounts_nothing(self):
        os.remove(os.path.join(self.moteur, "instance"))
        vu = self.vu()
        self.assertEqual(
            (False, "", False),
            (vu.instance_reelle, vu.ecosysteme, vu.plan_present),
        )

    def test_a_broken_site_link_mounts_nothing(self):
        """Le moteur suit le lien : un lien brisé ne monte aucun site."""
        os.remove(os.path.join(self.depots, SITE, "underlay.yml"))
        self.assertEqual("", self.vu().site)

    def test_a_broken_site_link_is_told_apart_from_no_link(self):
        """Le même geste règle les deux cas ; la ligne dit lequel, sans
        quoi elle redonnerait le geste sans dire pourquoi le précédent
        n'a rien monté."""
        lien = os.path.join(self.moteur, "underlay.yml")
        os.remove(os.path.join(self.depots, SITE, "underlay.yml"))
        brise = self.vu()
        os.remove(lien)
        aucun = self.vu()
        self.assertEqual(
            [state_screen.A_REGLER] * 2,
            [ligne(v, "Mounted site").etat for v in (brise, aucun)],
        )
        self.assertNotEqual(
            ligne(aucun, "Mounted site").detail,
            ligne(brise, "Mounted site").detail,
        )
        self.assertEqual((True, False), (brise.site_brise, aucun.site_brise))

    def test_a_site_link_to_a_folder_mounts_nothing_and_the_gesture_fixes_it(
        self,
    ):
        """Le moteur LIT `underlay.yml` : un lien qui mène à un dossier ne
        monte aucun site. La ligne le dit à régler, et son geste, rejoué
        depuis la racine avec le dossier frère du site, remplace ce lien."""
        lien = os.path.join(self.moteur, "underlay.yml")
        os.remove(lien)
        os.symlink(os.path.join("..", SITE), lien)
        vu = self.vu()
        self.assertEqual(("", True), (vu.site, vu.site_brise))
        l = ligne(vu, "Mounted site")
        self.assertEqual(state_screen.A_REGLER, l.etat)
        self.assertIn(f"{CHEMIN}/underlay.yml", l.detail)
        argv = shlex.split(l.detail[l.detail.index("ln -sfn") :])
        argv[-2] = argv[-2].replace(S.REPERE_SITE, SITE)
        subprocess.run(argv, cwd=self.racine, check=True)
        self.assertEqual(SITE, self.vu().site)


class TestLeReleveDeLaCle(CasDePoste):
    def test_the_verdict_is_the_exit_code(self):
        for code in (0, 1, 2):
            with self.subTest(code=code):
                self.voutes(code)
                self.assertEqual(code, self.vu().code_cle)

    def test_the_output_is_never_read_nor_kept(self):
        """Le faux imprime « cle presente » et sort en 1 : seul le code
        fait foi. Et le nom qu'il imprime ne se retrouve ni dans le relevé,
        ni dans l'écran, ni au terminal : les descripteurs 1 et 2 du
        processus qui relève n'en reçoivent rien."""
        self.voutes(1)
        with tempfile.TemporaryFile() as puits:
            sys.stdout.flush()
            sys.stderr.flush()
            gardes = [os.dup(1), os.dup(2)]
            try:
                os.dup2(puits.fileno(), 1)
                os.dup2(puits.fileno(), 2)
                vu = self.vu()
            finally:
                sys.stdout.flush()
                sys.stderr.flush()
                os.dup2(gardes[0], 1)
                os.dup2(gardes[1], 2)
                for garde in gardes:
                    os.close(garde)
            puits.seek(0)
            terminal = puits.read().decode("utf-8", "replace")
        self.assertEqual(1, vu.code_cle)
        self.assertNotIn(NOM_IMPRIME, terminal)
        self.assertNotIn(NOM_IMPRIME, repr(vu))
        texte = "\n".join(state_screen.render(S.lignes(vu)))
        self.assertNotIn(NOM_IMPRIME, texte)

    def test_the_probe_runs_in_the_engine_with_a_fresh_environment(self):
        """Hérité, l'environnement porterait `CONFIRMER`, les surcharges
        d'un make parent, ou un `SETOPS_INSTANCE` qui ferait juger la clé
        d'un autre écosystème."""
        heritage = {
            FUITE: "1",
            "CONFIRMER": "true",
            "MAKEFLAGS": "-j2",
            "MAKELEVEL": "1",
            "SETOPS_INSTANCE": "/nulle-part",
            "SETOPS_UNDERLAY": "/nulle-part",
            "ANSIBLE_CONFIG": "/nulle-part",
            "XDG_CONFIG_HOME": os.path.join(self.racine, "xdg"),
            "LANG": "C.UTF-8",
        }
        with mock.patch.dict(os.environ, heritage):
            self.vu()
        trace = self.trace()
        self.assertEqual(["etat"], trace["argv"])
        self.assertEqual(os.path.realpath(self.moteur), trace["cwd"])
        self.assertLessEqual(set(trace["env"]), set(S.ENV_TRANSMIS))
        # La liste de l'ÉPREUVE, et non la constante qu'elle éprouve :
        # élargir la liste transmise à l'un de ces noms doit rougir ici.
        self.assertEqual(
            [],
            [
                v
                for v in trace["env"]
                if v in (FUITE, "CONFIRMER")
                or v.startswith(("MAKE", "SETOPS_", "ANSIBLE_"))
            ],
        )
        self.assertIn("XDG_CONFIG_HOME", trace["env"])
        self.assertIn("HOME", trace["env"])

    def test_a_probe_past_its_delay_is_unknown(self):
        self.voutes(0, attente=5)
        debut = time.monotonic()
        with mock.patch.object(S, "DELAI", 0.5):
            vu = self.vu()
        self.assertIsNone(vu.code_cle)
        self.assertLess(time.monotonic() - debut, 4)

    def test_a_missing_script_is_unknown(self):
        os.remove(os.path.join(self.moteur, "scripts", "voutes.py"))
        self.assertIsNone(self.vu().code_cle)

    def test_the_probe_writes_nothing_in_the_engine(self):
        """Le faux importe un module voisin, comme le vrai : l'écran en
        lecture seule ne laisse rien derrière lui dans le moteur, pas même
        le bytecode de ces modules."""

        # Les liens sont suivis : le `.git` du moteur mène à son dépôt,
        # sous `.repo/projects/`.
        def fichiers():
            return sorted(
                os.path.relpath(os.path.join(d, f), self.moteur)
                for d, _s, fs in os.walk(self.moteur, followlinks=True)
                for f in fs
            )

        avant = fichiers()
        self.assertEqual(0, self.vu().code_cle)
        self.assertEqual(avant, fichiers())

    def test_without_an_instance_link_the_key_probe_is_not_run(self):
        """La ligne de la clé ne lit son code qu'avec un écosystème monté
        et son plan : sans eux, le code du moteur n'a pas à tourner."""
        os.remove(os.path.join(self.moteur, "instance"))
        self.assertIsNone(self.vu().code_cle)
        self.assertIsNone(self.trace())

    def test_without_a_plan_the_key_probe_is_not_run(self):
        os.remove(
            os.path.join(self.depots, ECOSYSTEME, "plan", "serveurs.yml")
        )
        self.assertIsNone(self.vu().code_cle)
        self.assertIsNone(self.trace())


class TestLeReleveDAnsible(CasDePoste):
    def test_an_unreadable_version_is_unknown(self):
        """Le code de retour fait foi avant la sortie : une version bien
        formée, dans la plage, imprimée par une sonde qui échoue, reste
        inconnue."""
        for corps in (
            "exit 1",
            "echo 2.18.6; exit 1",
            "echo 2.18.6; echo 2.19.0",
            "true",
        ):
            with self.subTest(corps=corps):
                self.python_du_venv(corps)
                self.assertIsNone(self.vu().version_ansible)

    def test_the_root_is_not_on_the_version_probe_path(self):
        """`-c` met le dossier courant en tête de `sys.path` : une
        distribution posée à la racine d'ERPLibre, d'où todo se lance, ne
        doit pas devenir la version lue."""
        ecrire(
            os.path.join(
                self.racine, "ansible_core-9.9.9.dist-info", "METADATA"
            ),
            "Metadata-Version: 2.1\nName: ansible-core\nVersion: 9.9.9\n",
        )
        self.python_du_venv(f'exec "{sys.executable}" "$@"')
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.racine)
        self.assertNotEqual("9.9.9", self.vu().version_ansible)

    def test_the_probes_read_nothing_from_the_menu_input(self):
        """Sous le menu, l'entrée est le terminal : une sonde qui la lirait
        prendrait les frappes de l'utilisateur, ou figerait l'écran."""
        lu = os.path.join(self.racine, "entree-lue")
        self.python_du_venv(f'cat > "{lu}"; echo 2.18.6')
        sortie, entree = os.pipe()
        os.write(entree, b"frappe-fictive-sanidine\n")
        os.close(entree)
        garde = os.dup(0)
        try:
            os.dup2(sortie, 0)
            vu = self.vu()
        finally:
            os.dup2(garde, 0)
            os.close(garde)
            os.close(sortie)
        with open(lu, encoding="utf-8") as f:
            self.assertEqual("", f.read())
        self.assertEqual("2.18.6", vu.version_ansible)

    def test_without_ansible_playbook_the_version_is_not_asked(self):
        os.remove(os.path.join(self.venv, "bin", "ansible-playbook"))
        vu = self.vu()
        self.assertEqual(
            (False, None), (vu.ansible_playbook, vu.version_ansible)
        )

    def test_the_range_is_read_in_the_engine_defaults(self):
        cas = {
            "serveur_ops_ansible: 'ansible-core>=2.18,<2.19'\n": PLAGE,
            "serveur_ops_ansible: ansible-core>=2.18,<2.19  # borne\n": PLAGE,
            "autre: 1\n" + DEFAUTS + "suite: 2\n": PLAGE,
            DEFAUTS + DEFAUTS: None,
            "serveur_ops_ansible_bis: x\n": None,
            "  serveur_ops_ansible: ansible-core>=2.18\n": None,
            "": None,
        }
        for texte, attendu in cas.items():
            with self.subTest(texte=texte):
                ecrire(
                    os.path.join(self.moteur, ansible_env.DEFAULTS_ANSIBLE),
                    texte,
                )
                self.assertEqual(attendu, self.vu().plage_ansible)

    def test_a_missing_defaults_file_is_unknown(self):
        os.remove(os.path.join(self.moteur, ansible_env.DEFAULTS_ANSIBLE))
        self.assertIsNone(self.vu().plage_ansible)


class TestLeReleveNeLanceQueSesSondes(CasDePoste):
    """LECTURE SEULE, jugée sur ce que le relevé LANCE : git en lecture,
    le Python du venv pour la version, `voutes.py etat`. Rien d'autre, et
    jamais une cible du moteur."""

    GIT_EN_LECTURE = {
        "rev-parse",
        "cat-file",
        "check-ignore",
        "status",
        "rev-list",
        "merge-base",
    }

    def lances(self):
        """Les argv de chaque processus que le relevé du poste démarre."""
        vrai = subprocess.Popen
        vus = []

        def espion(argv, *a, **k):
            vus.append(list(argv))
            return vrai(argv, *a, **k)

        with mock.patch.object(subprocess, "Popen", side_effect=espion):
            self.vu()
        return vus

    def permis(self, argv):
        voutes = os.path.join(self.moteur, "scripts", "voutes.py")
        if argv[:2] == ["git", "-C"] and len(argv) > 3:
            return argv[3] in self.GIT_EN_LECTURE
        if argv[:2] == [os.path.join(self.venv, "bin", "python"), "-c"]:
            return True
        # La sonde du mineur lance « python3 » NU, et c'est le propos :
        # elle mesure ce que verra la garde du moteur, qui fait de même.
        if argv == ["python3", "-c", ansible_env.SONDE_MINEUR]:
            return True
        return (
            argv[0] == sys.executable
            and argv[-2:] == [voutes, "etat"]
            and all(option.startswith("-") for option in argv[1:-2])
        )

    def test_every_process_started_is_one_of_its_probes(self):
        vus = self.lances()
        self.assertTrue(vus, "rien n'a été lancé : rien n'est prouvé")
        self.assertEqual([], [a for a in vus if not self.permis(a)])

    def test_the_engine_makefile_is_never_run(self):
        trace = os.path.join(self.depots, "trace-make-fictive")
        regle_piege = f"\ttouch {shlex.quote(trace)}\n"
        ecrire(
            os.path.join(self.moteur, "Makefile"),
            "%:\n" + regle_piege + ".DEFAULT:\n" + regle_piege,
        )
        self.vu()
        self.assertFalse(os.path.exists(trace))


class TestLeReleveNeLeveJamais(CasDeLangue):
    def test_an_empty_or_missing_root_gives_a_survey(self):
        with tempfile.TemporaryDirectory() as vide_:
            for racine in (vide_, os.path.join(vide_, "absente")):
                with self.subTest(racine=racine):
                    vu = S.releve(racine)
                    self.assertEqual("", vu.chemin)
                    self.assertFalse(vu.moteur_present)
                    self.assertEqual(10, len(S.lignes(vu)))

    TOUS_LES_OUTILS = S.OUTILS_COEUR + tuple(o for o, _ in S.OUTILS_GESTES)

    def test_every_missing_tool_is_listed(self):
        """Chaque outil, du cœur comme d'un geste, est demandé au système :
        un seul absent, et c'est lui que le relevé nomme."""
        for outil in self.TOUS_LES_OUTILS:
            with self.subTest(outil=outil), tempfile.TemporaryDirectory() as r:
                with mock.patch.object(
                    S.shutil,
                    "which",
                    side_effect=lambda o, a=outil: None if o == a else "/x",
                ):
                    vu = S.releve(r)
                self.assertEqual((outil,), vu.outils_absents)

    def test_a_missing_core_tool_is_seen_end_to_end(self):
        for outil in S.OUTILS_COEUR:
            with self.subTest(outil=outil), tempfile.TemporaryDirectory() as r:
                with mock.patch.object(
                    S.shutil,
                    "which",
                    side_effect=lambda o, a=outil: None if o == a else "/x",
                ):
                    l = ligne(S.releve(r), "Station tools")
                self.assertEqual(state_screen.A_REGLER, l.etat)
                self.assertIn(outil, l.detail)

    def test_a_tool_probe_that_raises_counts_the_tool_missing(self):
        """Ne pas savoir si un outil est là n'est pas savoir qu'il y est."""
        with tempfile.TemporaryDirectory() as racine:
            with mock.patch.object(S.shutil, "which", side_effect=OSError):
                vu = S.releve(racine)
        self.assertEqual(self.TOUS_LES_OUTILS, vu.outils_absents)
        self.assertNotEqual(
            state_screen.PORTE, ligne(vu, "Station tools").etat
        )

    def test_a_platform_probe_that_raises_is_never_carried(self):
        with tempfile.TemporaryDirectory() as racine:
            with mock.patch.object(S.platform, "system", side_effect=OSError):
                vu = S.releve(racine)
        self.assertEqual("", vu.systeme)
        self.assertNotEqual(state_screen.PORTE, ligne(vu, "Platform").etat)


if __name__ == "__main__":
    unittest.main()
