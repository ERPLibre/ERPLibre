# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce qu'OpenUpgrade DÉCLARE changer, pour l'opposer à ce qui a changé.

Le rapport de qualité comptait des « + » et des « − ». C'est vrai mais
insuffisant : un champ qui cesse d'être stocké disparaît de la base sans
rien perdre — il est calculé maintenant. Compté comme une perte, il
alarme ; ignoré, il masquerait une vraie perte. Il faut un troisième
état, et OpenUpgrade le connaît déjà.

Chaque module cœur d'Odoo porte, dans OpenUpgrade, un fichier
`upgrade_analysis.txt` qui liste ce que le palier change :

    ---Models in module 'account'---
    obsolete model account.unreconcile [transient]
    new model product.combo (renamed from pos.combo in module point_of_sale)
    ---Fields in module 'account'---
    account / account.account / code (char) : not stored anymore
    account / account.cash.rounding / loss_account_id (many2one) : needs
        conversion to v18-style company dependent

C'est la même information que la page « coverage analysis » publiée par
l'OCA — elle est engendrée depuis ces fichiers — mais lue dans le dépôt,
donc sans réseau, et à la version exacte du checkout.

Ce qu'on n'y trouvera pas
-------------------------
Ces fichiers ne couvrent que les modules CŒUR d'Odoo. Un champ d'un
module OCA ou maison n'y sera jamais, et son absence ne veut donc pas
dire « perte non déclarée » au même titre. Le rapport le dit plutôt que
de laisser conclure.
"""

import os
import re

REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

# `new model x.y [transient]` ou `new model x.y (renamed from a.b in module m)`
MODELE_NEUF = re.compile(
    r"^new model (\S+)(?:\s+\(renamed from (\S+) in module (\S+)\))?"
)
MODELE_OBSOLETE = re.compile(r"^obsolete model (\S+)")
# `module / model / champ (type)   : description` — le type est absent sur
# les pseudo-champs comme `_order`, et le « : » n'est pas toujours espacé.
CHAMP = re.compile(
    r"^(\S+)\s+/\s+(\S+)\s+/\s+(\S+)\s*(?:\(([^)]*)\))?\s*:\s*(.*)$"
)
# `module is now 'sale' ('point_of_sale')`
DEPLACE = re.compile(r"module is now '([^']+)'")

SECTIONS = {
    "Models": "model",
    "Fields": "field",
    "XML records": "xml",
}


def scripts_dir(version, root=None):
    """Où vivent les analyses pour ce palier d'ARRIVÉE."""
    return os.path.join(
        root or REPO_ROOT,
        f"odoo{version}.0",
        "OCA_OpenUpgrade",
        "openupgrade_scripts",
        "scripts",
    )


def analysis_files(version, root=None):
    """Les `upgrade_analysis.txt` de ce palier, triés.

    On filtre sur le dossier de version : à côté des `18.0.1.0` vivent un
    `tests` et, en 14, un `0.0` — les lire mélangerait les paliers.
    """
    base = scripts_dir(version, root)
    trouves = []
    if not os.path.isdir(base):
        return trouves
    prefixe = f"{version}."
    for module in sorted(os.listdir(base)):
        dossier = os.path.join(base, module)
        if not os.path.isdir(dossier):
            continue
        for release in sorted(os.listdir(dossier)):
            if not release.startswith(prefixe):
                continue
            chemin = os.path.join(dossier, release, "upgrade_analysis.txt")
            if os.path.isfile(chemin):
                trouves.append(chemin)
    return trouves


_CACHE_MODULES = {}


def analysed_modules(version, root=None):
    """Les modules cœur qu'OpenUpgrade analyse à ce palier.

    Les noms de dossiers SONT la liste. Elle sert à distinguer « aucune
    déclaration » de « hors de son champ » : OpenUpgrade ne dit rien d'un
    module OCA, et le compter comme non déclaré accuserait à tort.
    """
    if version in _CACHE_MODULES:
        return _CACHE_MODULES[version]
    base = scripts_dir(version, root)
    trouves = set()
    if os.path.isdir(base):
        trouves = {
            nom
            for nom in os.listdir(base)
            if os.path.isdir(os.path.join(base, nom))
        }
    if root is None:
        _CACHE_MODULES[version] = trouves
    return trouves


def blank_index():
    return {
        "models_new": set(),
        "models_obsolete": set(),
        "models_renamed": {},
        "fields_new": set(),
        "fields_del": set(),
        "fields_unstored": set(),
        "fields_stored": set(),
        "fields_moved": {},
        "fields_company_dependent": set(),
        "fields_other": {},
        "xml_new": 0,
        "xml_del": 0,
        "modules": 0,
    }


def classify(description):
    """La catégorie d'un changement de champ, d'après sa description.

    L'ordre compte : « NEW relation: … » commence par NEW, et
    « not stored anymore » contient « stored ». On teste donc du plus
    précis au plus général plutôt que par appartenance de sous-chaîne.
    """
    texte = description.strip()
    if texte.startswith("NEW"):
        return "new"
    if texte.startswith("DEL"):
        return "del"
    if texte.startswith("not stored anymore"):
        return "unstored"
    if texte.startswith("is now stored"):
        return "stored"
    if "needs conversion to" in texte and "company dependent" in texte:
        return "company_dependent"
    if DEPLACE.search(texte):
        return "moved"
    return "other"


def parse(texte, index=None):
    """Lire UN fichier d'analyse dans l'index (créé au besoin)."""
    index = blank_index() if index is None else index
    section = None
    for ligne in texte.splitlines():
        entete = re.match(r"^---(.+?) in module '([^']+)'---", ligne)
        if entete:
            section = SECTIONS.get(entete.group(1))
            continue
        if not ligne.strip():
            continue
        if section == "model":
            _read_model(ligne, index)
        elif section == "field":
            _read_field(ligne, index)
        elif section == "xml":
            if ligne.startswith("NEW"):
                index["xml_new"] += 1
            elif ligne.startswith("DEL"):
                index["xml_del"] += 1
    return index


def _read_model(ligne, index):
    trouve = MODELE_NEUF.match(ligne)
    if trouve:
        index["models_new"].add(trouve.group(1))
        if trouve.group(2):
            # Le renommage se lit du côté du NOUVEAU modèle : c'est là
            # qu'OpenUpgrade note d'où il vient. L'ancien n'apparaît nulle
            # part comme « obsolete », donc sans cette ligne sa
            # disparition passerait pour une perte sèche.
            index["models_renamed"][trouve.group(2)] = trouve.group(1)
        return
    trouve = MODELE_OBSOLETE.match(ligne)
    if trouve:
        index["models_obsolete"].add(trouve.group(1))


def _read_field(ligne, index):
    trouve = CHAMP.match(ligne)
    if not trouve:
        return
    _module, modele, champ, _type, description = trouve.groups()
    if champ.startswith("_"):
        # `_order`, `_sql_constraints` : ce ne sont pas des champs, et les
        # compter fausserait le rapprochement avec `ir_model_fields`.
        return
    cle = f"{modele}.{champ}"
    genre = classify(description)
    if genre == "new":
        index["fields_new"].add(cle)
    elif genre == "del":
        index["fields_del"].add(cle)
    elif genre == "unstored":
        index["fields_unstored"].add(cle)
    elif genre == "stored":
        index["fields_stored"].add(cle)
    elif genre == "company_dependent":
        index["fields_company_dependent"].add(cle)
    elif genre == "moved":
        index["fields_moved"][cle] = DEPLACE.search(description).group(1)
    else:
        index["fields_other"].setdefault(cle, []).append(description.strip())


def load(version, root=None):
    """L'index complet d'un palier. `modules` à 0 = rien de lisible."""
    index = blank_index()
    for chemin in analysis_files(version, root):
        try:
            with open(chemin, "r", encoding="utf-8") as handle:
                parse(handle.read(), index)
        except OSError:
            continue
        index["modules"] += 1
    return index


def model_change(nom, index):
    """Ce qu'OpenUpgrade déclare pour ce modèle disparu, ou None."""
    if nom in index["models_renamed"]:
        return ("renamed", index["models_renamed"][nom])
    if nom in index["models_obsolete"]:
        return ("obsolete", None)
    return None


def field_change(cle, index):
    """Ce qu'OpenUpgrade déclare pour ce champ disparu, ou None.

    « unstored » est le cas qui justifie tout l'outil : le champ EXISTE
    toujours, il n'a plus de colonne parce qu'il est calculé. Ce n'est ni
    un gain ni une perte — c'est une transformation, et la confondre avec
    une perte fait crier au loup à chaque palier.
    """
    if cle in index["fields_del"]:
        return ("del", None)
    if cle in index["fields_unstored"]:
        return ("unstored", None)
    if cle in index["fields_company_dependent"]:
        return ("company_dependent", None)
    if cle in index["fields_moved"]:
        return ("moved", index["fields_moved"][cle])
    return None
