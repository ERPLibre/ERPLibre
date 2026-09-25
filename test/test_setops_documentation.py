#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les modes d'emploi de Set-OPS suivent le code qu'ils décrivent.

Une prose recopie des vocabulaires clos — les relations à l'épingle, les
dix segments, les trois états — et des gestes que l'écran nomme. Une copie
ne suit pas ce qu'elle copie : un terme ajouté au code et absent de la page
se lit comme un terme qui n'existe pas, et un geste renommé envoie chercher
un fichier absent.

Le contrôle porte sur les SOURCES bilingues (`.base.md`) et sur CHAQUE
langue : une ligne retirée d'une seule moitié laisserait l'autre complète,
et un contrôle sur le texte entier ne verrait rien.
"""

import inspect
import os
import re
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.setops import ansible_env, engine, state  # noqa: E402

# Les modules du paquet, dans l'ordre où le README les présente. Un module
# neuf entre ici, et ses fonctions publiques doivent alors être nommées dans
# les deux langues de la page.
MODULES = (engine, state, ansible_env)
from script.todo import state_screen, todo_i18n  # noqa: E402
from script.todo.todo_i18n import TRANSLATIONS  # noqa: E402

PAQUET_README = os.path.join(RACINE, "script", "setops", "README.base.md")
DOC_SETOPS = os.path.join(RACINE, "doc", "SETOPS.base.md")


def texte(chemin):
    with open(chemin, encoding="utf-8") as fichier:
        return fichier.read()


def aplati(texte):
    """`texte` en minuscules, chaque suite de blancs réduite à une espace."""
    return " ".join(texte.split()).lower()


def rangees(texte):
    """Les rangées des tables Markdown de `texte`, chacune en liste de
    cellules aplaties, emphase et code en ligne ôtés."""
    return [
        [aplati(cellule.strip().strip("`*_")) for cellule in ligne.split("|")]
        for ligne in texte.splitlines()
        if ligne.lstrip().startswith("|")
    ]


MARQUEUR = re.compile(r"^<!-- \[(\w+)\] -->$", re.M)


def moities(chemin):
    """((langue, texte), ...) pour l'anglais et le français.

    Chaque bloc va à la langue de son marqueur mmg ; un bloc `[common]`
    n'appartient à aucune des deux, et ce qui précède le premier marqueur
    non plus.
    """
    par_langue = {"en": [], "fr": []}
    morceaux = MARQUEUR.split(texte(chemin))
    for langue, bloc in zip(morceaux[1::2], morceaux[2::2]):
        if langue in par_langue:
            par_langue[langue].append(bloc)
    return tuple((l, "".join(blocs)) for l, blocs in par_langue.items())


# Un nom en code dans la page, suivi ou non de ses paramètres entre
# parenthèses : `nom` ou `nom(a, b)`.
NOM_CITE = re.compile(r"`(\w+)(?:\(([^()`]*)\))?`")


# Une énumération : des noms en code séparés par des virgules, le dernier
# éventuellement par « and », « or », « et » ou « ou », retours à la ligne
# compris.
ENUMERATION = re.compile(
    r"`\w+`(?:(?:\s*,\s*|\s*,?\s+(?:and|or|et|ou)\s+)`\w+`)+"
)


def enumerations_des_relations(moitie):
    """Les énumérations de `moitie` qui nomment plus d'une relation à
    l'épingle, chacune en ensemble de noms. Elles se lisent par leur forme,
    et non par ligne : recouper une énumération n'en change rien."""
    return [
        noms
        for noms in (
            set(re.findall(r"`(\w+)`", suite))
            for suite in ENUMERATION.findall(moitie)
        )
        if len(noms & set(engine.RELATIONS)) > 1
    ]


def publiques(module):
    """Les fonctions que `module` définit lui-même, hors noms en « _ »."""
    return sorted(
        nom
        for nom, objet in vars(module).items()
        if inspect.isfunction(objet)
        and objet.__module__ == module.__name__
        and not nom.startswith("_")
    )


def releve_du_poste(**champs):
    """Un relevé où le moteur que déclare le vrai manifeste est présent et
    réglé, `champs` par-dessus : chaque épreuve n'écarte que ce qu'elle
    regarde."""
    declaration = engine.declaration(RACINE)
    vu = {
        "systeme": "Linux",
        "chemin": declaration.path,
        "revision": declaration.revision,
        "parent_ignore": True,
        "outil_repo": True,
        "repo_initialise": True,
        "chemin_occupe": True,
        "moteur_present": True,
        "gere_par_repo": True,
        "arbre_repo": True,
        "relation": engine.EGAL,
        "ecart": 0,
        "modifies": 0,
        "ansible_playbook": False,
        "version_ansible": None,
        "plage_ansible": None,
        "instance_reelle": False,
        "ecosysteme": "",
        "plan_present": False,
        "site": "",
        "site_brise": False,
        "code_cle": None,
        "outils_absents": (),
        "mineur_path": ansible_env.MINEUR_CIBLE,
        "biblios_ecarts": (),
        "collections_ecarts": (),
        "biblios_epinglees": (),
        "collections_epinglees": (),
    }
    vu.update(champs)
    return state.Releve(**vu)


class TestLeModeDEmploiDuPaquet(unittest.TestCase):
    def test_every_call_it_writes_has_the_parameters_of_the_code(self):
        """Une fonction écrite avec ses parenthèses existe dans l'un des
        modules du paquet, et ses paramètres sont ceux de sa signature, dans l'ordre :
        un paramètre renommé dans le code et gardé dans la page se lit
        comme un paramètre qui existe."""
        for langue, moitie in moities(PAQUET_README):
            appels = [
                prise.groups()
                for prise in NOM_CITE.finditer(moitie)
                if prise.group(2) is not None
            ]
            with self.subTest(langue=langue):
                self.assertTrue(appels, "aucun appel écrit dans la page")
            for nom, params in appels:
                with self.subTest(langue=langue, appel=nom):
                    fonction = next(
                        (
                            trouve
                            for module in MODULES
                            for trouve in (getattr(module, nom, None),)
                            if trouve is not None
                        ),
                        None,
                    )
                    self.assertTrue(
                        inspect.isfunction(fonction), f"{nom} n'existe pas"
                    )
                    self.assertEqual(
                        list(inspect.signature(fonction).parameters),
                        [p.strip() for p in params.split(",") if p.strip()],
                    )

    def test_every_public_function_is_named(self):
        """Chaque fonction publique du paquet est nommée dans chaque
        langue : une fonction ajoutée au paquet sans sa ligne dans la page
        n'a pas de rôle écrit."""
        for module in MODULES:
            with self.subTest(module=module.__name__):
                self.assertTrue(publiques(module))
        for langue, moitie in moities(PAQUET_README):
            nommes = {nom for nom, _params in NOM_CITE.findall(moitie)}
            for module in MODULES:
                for nom in publiques(module):
                    with self.subTest(langue=langue, fonction=nom):
                        self.assertIn(nom, nommes)

    def test_the_relations_to_the_pin_are_exactly_those_of_the_code(self):
        """Sur LA LISTE qui les énumère, et non sur la page : une relation
        retirée de la liste se retrouve nommée ailleurs dans la page, et une
        relation ôtée du code resterait listée."""
        for langue, moitie in moities(PAQUET_README):
            with self.subTest(langue=langue):
                enumerations = enumerations_des_relations(moitie)
                self.assertEqual(1, len(enumerations), enumerations)
                self.assertEqual(set(engine.RELATIONS), enumerations[0])

    def test_the_relations_guard_reads_the_list_not_its_lines(self):
        """Contrôle du garde ci-dessus sur des pages posées ici : recouper
        la liste ou la finir par « and » la laisse juste ; une relation
        retirée de la liste, même nommée plus loin, ou un terme de trop, la
        rend fausse."""
        noms = [f"`{r}`" for r in engine.RELATIONS]
        sans_absente = [n for n in noms if n != f"`{engine.ABSENTE}`"]
        cas = {
            "une ligne": (", ".join(noms), True),
            "recoupée": (
                ", ".join(noms[:3]) + ",\n" + ", ".join(noms[3:]),
                True,
            ),
            "finie par and": (
                ", ".join(noms[:-1]) + " and\n" + noms[-1],
                True,
            ),
            "sans absente": (", ".join(sans_absente), False),
            "sans absente, recoupée": (
                ", ".join(sans_absente[:3])
                + ",\n"
                + ", ".join(sans_absente[3:]),
                False,
            ),
            "un terme de trop": (
                ", ".join(noms + ["`relation_fictive_zoisite`"]),
                False,
            ),
        }
        for nom, (liste, juste) in cas.items():
            page = (
                f"A closed vocabulary: {liste}.\nOnly `{engine.ABSENTE}` is"
                f" a finding; the last term, `{engine.INCONNUE}`, establishes"
                " nothing.\n"
            )
            with self.subTest(cas=nom):
                enumerations = enumerations_des_relations(page)
                self.assertEqual(
                    juste,
                    enumerations == [set(engine.RELATIONS)],
                    enumerations,
                )

    def test_every_exit_code_of_the_entry_point_is_named(self):
        for langue, moitie in moities(PAQUET_README):
            for code in (
                engine.RC_OK,
                engine.RC_DECLARATION,
                engine.RC_OCCUPE,
            ):
                with self.subTest(langue=langue, code=code):
                    self.assertRegex(moitie, rf"`{code}`")


class TestLaDocumentationSetops(unittest.TestCase):
    def test_the_enumeration_names_every_segment_in_its_language(self):
        """Dans LE paragraphe qui les énumère — celui qui en nomme le plus —
        et par leur nom traduit, tel que l'écran l'affiche : un segment
        retiré de l'énumération reste souvent nommé ailleurs dans la page.
        La casse et le retour à la ligne ne comptent pas."""
        for langue, moitie in moities(DOC_SETOPS):
            noms = [aplati(TRANSLATIONS[s][langue]) for s in state.SEGMENTS]
            paragraphes = [aplati(p) for p in moitie.split("\n\n")]
            enumeration = max(
                paragraphes, key=lambda p: sum(nom in p for nom in noms)
            )
            # Le plus long d'abord, et chacun CONSOMMÉ une fois : « moteur »
            # se lit aussi dans « manifeste du moteur », et ne doit compter
            # que s'il figure pour lui-même.
            for nom in sorted(noms, key=len, reverse=True):
                with self.subTest(langue=langue, segment=nom):
                    self.assertTrue(nom in enumeration, f"« {nom} » absent")
                enumeration = enumeration.replace(nom, "", 1)

    def test_every_state_is_explained_with_its_mark_and_its_label(self):
        """La table des états porte, SUR UNE MÊME RANGÉE, la marque de
        l'état et son libellé traduit, tels que l'écran les imprime.

        C'est la seule ancre du SENS des marques : deux marques interverties
        dans `state_screen.MARQUES` gardent chacune un libellé dans la page,
        et seule la rangée dit laquelle va avec lequel. La rangée qui porte
        le libellé d'un état porte sa marque, et aucune autre marque
        d'état."""
        libelles = {
            state_screen.PORTE: "carried",
            state_screen.A_REGLER: "to set up here",
            state_screen.ABSENT: "not in the repository",
        }
        self.assertEqual(set(state_screen.ETATS), set(libelles))
        marques = set(state_screen.MARQUES.values())
        for langue, moitie in moities(DOC_SETOPS):
            table = rangees(moitie)
            for etat, cle in libelles.items():
                libelle = aplati(TRANSLATIONS[cle][langue])
                with self.subTest(langue=langue, etat=etat):
                    porteuses = [r for r in table if libelle in r]
                    self.assertEqual(
                        1, len(porteuses), f"« {libelle} » : {porteuses}"
                    )
                    self.assertEqual(
                        {state_screen.MARQUES[etat]},
                        marques & set(porteuses[0]),
                        porteuses[0],
                    )

    def test_the_gestures_it_names_are_those_the_screen_names(self):
        """Le script de rapatriement et l'installation de repo : la page et
        l'écran envoient au même endroit, et l'endroit existe."""
        page = texte(DOC_SETOPS)
        for geste in (state.RAPATRIER, state.INSTALLER_REPO):
            with self.subTest(geste=geste):
                self.assertIn(geste, page)
                self.assertTrue(os.path.isfile(os.path.join(RACINE, geste)))

    def test_the_migration_command_is_the_one_the_code_names(self):
        """Le `mv` de la page est celui que le script de rapatriement et
        l'écran affichent, pour le chemin que déclare le manifeste."""
        declaration = engine.declaration(RACINE)
        self.assertIsNotNone(declaration)
        self.assertIn(engine.mise_de_cote(declaration.path), texte(DOC_SETOPS))

    def test_the_exit_codes_of_the_fetch_are_named(self):
        """Les codes que le module rend au script de rapatriement, et que le
        script rend à son tour, sont écrits dans chaque langue."""
        for langue, moitie in moities(DOC_SETOPS):
            for code in (engine.RC_DECLARATION, engine.RC_OCCUPE):
                with self.subTest(langue=langue, code=code):
                    self.assertRegex(moitie, rf"`{code}`")

    def test_the_interpreter_the_path_guard_needs_is_named(self):
        """La garde du chemin tourne dans l'interpréteur d'ERPLibre : sans
        lui, un lancement ne nomme pas ce qui occupe le chemin, et chaque
        langue le dit."""
        for langue, moitie in moities(DOC_SETOPS):
            with self.subTest(langue=langue):
                self.assertIn("`.venv.erplibre/bin/python`", moitie)

    def test_the_commands_it_quotes_are_those_the_screen_prints(self):
        """Le geste qui monte un site et la question que la ligne de
        l'emplacement pose à git, pour le chemin que déclare le manifeste :
        la page les cite tels que l'écran les imprime, pour qu'ils se
        recopient."""
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"
        page = texte(DOC_SETOPS)
        rendu = dict(zip(state.SEGMENTS, state.lignes(releve_du_poste())))
        gabarit = TRANSLATIONS["no site mounted: {cmd}"]["en"]
        detail = rendu[state.SITE].detail
        prefixe = gabarit.split("{cmd}")[0]
        self.assertTrue(detail.startswith(prefixe), detail)
        for nom, commande in (
            ("site", detail[len(prefixe) :]),
            ("emplacement", rendu[state.EMPLACEMENT].source),
        ):
            with self.subTest(commande=nom):
                self.assertIn(commande, page)

    def test_the_menu_path_is_the_breadcrumb(self):
        from script.todo.todo import TODO

        chemin = TODO.menu_path(
            "run",
            "prompt_execute",
            "prompt_execute_deploy",
            "prompt_execute_setops",
        )
        for langue, moitie in moities(DOC_SETOPS):
            with self.subTest(langue=langue):
                self.assertIn(chemin, moitie)

    def test_the_readme_tables_link_the_page_in_both_languages(self):
        for langue, moitie in moities(os.path.join(RACINE, "README.base.md")):
            with self.subTest(langue=langue):
                self.assertTrue(
                    "(doc/SETOPS.md)" in moitie,
                    "lien vers doc/SETOPS.md absent",
                )


if __name__ == "__main__":
    unittest.main()
