#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'extension GNOME vue des tests d'ERPLibre.

L'extension est un dépôt à part, cloné dans
script/gnome-extension/erplibre_home/ par Google Repo ou par
install_erplibre_home.sh : un checkout peut ne pas l'avoir. Un test qui lit
un de ses fichiers porte SANS_EXTENSION, et se dit sauté, avec la commande
qui la clone, au lieu d'échouer sur un fichier absent. metadata.json est le
témoin, comme pour erplibre_home_extension_present de
erplibre_home_settings.sh. L'extension elle-même se teste dans son dépôt.

Ce qu'un test lit du clone passe par CONTRACT.md : les fonctions
ci-dessous en tirent sa version, le tableau D-Bus, l'objet et l'interface,
le tableau des enregistrements et celui des réglages que pilote Odoo. Les
fixtures partagées de streamdeck.conf et de keymap.json, que le contrat
décrit, sont les seuls autres fichiers lus : des données, que les tests
des deux dépôts passent chacun à leur propre code.

Sans le préfixe test_, le lanceur unitaire ne prend pas ce module pour un
fichier de tests.
"""

import json
import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
CHEMIN = "script/gnome-extension/erplibre_home"
EXTENSION = RACINE / CHEMIN
PRESENTE = (EXTENSION / "metadata.json").is_file()

SANS_EXTENSION = unittest.skipUnless(
    PRESENTE, CHEMIN + " absent : make erplibre_home_install_extension"
)

# Les types D-Bus simples : chacun compte pour un argument.
TYPES_SIMPLES = "ybnqiuxtdsogh"


def contrat():
    """Le texte de CONTRACT.md du clone.

    Les tests d'ERPLibre ne lisent du clone que ce que CONTRACT.md énonce,
    et les valeurs qu'il donne : le code de l'extension, sa forme, ses
    noms de constantes et l'endroit où elles vivent, changent librement
    tant que ses propres tests le tiennent au contrat."""
    return (EXTENSION / "CONTRACT.md").read_text(encoding="utf-8")


def contrat_a_plat():
    """CONTRACT.md, chaque suite de blancs réduite à une espace : une
    valeur que le texte coupe en fin de ligne se lit d'un seul tenant."""
    return re.sub(r"\s+", " ", contrat())


def valeur_du_contrat(motif):
    """La valeur que donne le groupe 1 de `motif` dans le contrat à plat,
    la même à chaque occurrence ; AssertionError s'il n'en donne aucune ou
    en donne plusieurs."""
    trouves = set(re.findall(motif, contrat_a_plat()))
    if len(trouves) != 1:
        raise AssertionError(
            "CONTRACT.md : %s donne %s" % (motif, sorted(trouves))
        )
    return trouves.pop()


def objet_et_interface():
    """(chemin d'objet, interface) que le contrat donne au bus D-Bus."""
    return (
        valeur_du_contrat(r"object `(/[^`]+)`"),
        valeur_du_contrat(r"interface `([\w.]+)`"),
    )


def methodes_promises():
    """{méthode: nombre d'arguments d'entrée} du tableau D-Bus du
    contrat. Chaque type d'entrée y est simple, d'une lettre : un type
    composé lèverait plutôt que de se compter faux."""
    methodes = {}
    for nom, entree in re.findall(
        r"^\s*\| `(\w+)` \|\s*`?([a-z]*)`?\s*\| `[a-z]+` \|$",
        contrat(),
        re.M,
    ):
        if entree.strip(TYPES_SIMPLES):
            raise AssertionError("%s : type composé %s" % (nom, entree))
        methodes[nom] = len(entree)
    return methodes


def enregistrements():
    """{enregistrement: {clé: type}} du tableau des enregistrements du
    contrat ; le type est text, integer ou number."""
    tableau = {}
    for nom, cle, type_ in re.findall(
        r"^\s*\| `([^`]+)` \| `(\w+)` \| (text|integer|number)\b",
        contrat(),
        re.M,
    ):
        tableau.setdefault(nom, {})[cle] = type_
    return tableau


def version_du_contrat():
    """(MAJEURE, MINEURE) de la ligne « **Contract version: X.Y** » du
    contrat ; AssertionError s'il n'en porte pas exactement une."""
    versions = re.findall(
        r"^\*\*Contract version: (\d+)\.(\d+)\*\*$", contrat(), re.M
    )
    if len(versions) != 1:
        raise AssertionError("CONTRACT.md : versions %s" % versions)
    return tuple(int(nombre) for nombre in versions[0])


def reglages_du_contrat():
    """{clé du fil: (ligne de streamdeck.conf, cellule des valeurs)} du
    tableau des réglages que pilote Odoo : chaque rangée « | `clé` |
    `LIGNE` | valeurs | » du contrat, la clé en minuscules, la ligne en
    majuscules, la cellule sans ses blancs de bord. Une clé qui revient
    lève AssertionError plutôt que de cacher sa première rangée."""
    tableau = {}
    for cle, ligne, valeurs in re.findall(
        r"^\s*\| `([a-z][a-z0-9_]*)` \| `([A-Z][A-Z0-9_]*)` \|([^|\n]*)\|",
        contrat(),
        re.M,
    ):
        if cle in tableau:
            raise AssertionError("CONTRACT.md : %s deux fois" % cle)
        tableau[cle] = (ligne, valeurs.strip())
    return tableau


def fixtures_de_reglages():
    """[(nom, octets lus, réglages du fil, lignes, octets réécrits)] des
    fixtures partagées de test/fixtures/streamdeck_conf/ du clone, triées
    par nom, sous la forme que décrit le contrat : <nom>.in.conf, le
    fichier avant ; <nom>.json, dont `settings` porte les valeurs du fil et
    `lines` la valeur que chacune donne à sa ligne « CLÉ= », dans l'ordre
    où une ligne absente s'ajoute ; <nom>.out.conf, les octets une fois
    `lines` écrites. Une fixture à laquelle manque l'un des trois lève
    AssertionError."""
    dossier = EXTENSION / "test/fixtures/streamdeck_conf"
    fixtures = []
    for entree in sorted(dossier.glob("*.in.conf")):
        nom = entree.name[: -len(".in.conf")]
        donnees = dossier / (nom + ".json")
        reecrit = dossier / (nom + ".out.conf")
        if not (donnees.is_file() and reecrit.is_file()):
            raise AssertionError("fixture %s incomplète" % nom)
        valeurs = json.loads(donnees.read_text(encoding="utf-8"))
        fixtures.append(
            (
                nom,
                entree.read_bytes(),
                valeurs["settings"],
                valeurs["lines"],
                reecrit.read_bytes(),
            )
        )
    return fixtures


# Les clés de chaque fixture de keymap.json que l'article 11 du contrat
# énonce ; une MINEURE peut en ajouter, aucune ne peut manquer.
CLES_DES_DISPOSITIONS = (
    "catalog",
    "plugins_off",
    "layouts",
    "valid",
    "loader",
)


def fixtures_de_dispositions():
    """[(nom, cas)] des fixtures partagées de test/fixtures/keymap/ du
    clone, triées par nom, sous la forme que décrit le contrat : chaque
    <nom>.json porte `catalog` (une sortie de --catalog), `plugins_off`,
    `layouts` (les key_layouts d'une réponse), `valid`, ce que l'extension
    en écrit, et `loader`, ce que le chargeur d'ERPLibre en fait. Une
    fixture à laquelle manque l'une de ces clés lève AssertionError."""
    dossier = EXTENSION / "test/fixtures/keymap"
    fixtures = []
    for chemin in sorted(dossier.glob("*.json")):
        cas = json.loads(chemin.read_text(encoding="utf-8"))
        if not isinstance(cas, dict):
            raise AssertionError("fixture %s : pas un objet" % chemin)
        manque = [c for c in CLES_DES_DISPOSITIONS if c not in cas]
        if manque:
            raise AssertionError("fixture %s : manque %s" % (chemin, manque))
        fixtures.append((chemin.stem, cas))
    return fixtures
