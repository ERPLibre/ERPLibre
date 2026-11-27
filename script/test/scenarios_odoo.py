# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les scénarios du générateur de code : leur schéma, leurs phases, et les
transformations de fichiers qu'ils demandent. Des fonctions pures, sans
processus ni base : le pilote d'un scénario (scenario_odoo.py) et la
campagne (run_odoo_scenarios.py) les appellent.

Un scénario est une entrée de script/test/config_testcase.odoo<V>.json,
sous la clé racine « lst_test ». Deux sortes :

- « run_command » : un script lancé seul, sans argument (`script`, ou
  `script_coverage` sous --coverage) ;
- « run_test_exec » : copie du dépôt dans un bac à sable, installation des
  modules, régénération par le générateur, puis contrôle que le code
  régénéré est identique au code commité.

Le schéma est STRICT : une clé inconnue, une clé d'une autre sorte, un
type faux, une clé obligatoire absente ou un nom en double refusent le
fichier entier, et le message nomme l'entrée. Une faute de frappe dans une
clé facultative ne passe donc plus pour une clé absente. Les entrées
désactivées sont validées comme les autres : on les réactive telles
quelles.

`sequence` est la PHASE de l'entrée : la phase N+1 ne démarre qu'à la fin
de la phase N.
"""

import configparser
import fnmatch
import io
import json
import os
import re
import uuid

from script.test import lanceur

# Clés communes aux deux sortes : nom -> type attendu.
_COMMUNES = {
    "test_name": str,
    "sequence": int,
    "disable": bool,
    "note": str,
}

_COMMANDE = {
    "run_command": bool,
    "script": str,
    # Le script lancé à sa place sous --coverage.
    "script_coverage": str,
    # Chemins, relatifs à la racine du dépôt, que le script modifie sur le
    # dépôt D'ORIGINE et rétablit lui-même : restaurés par git si le
    # scénario est tué avant.
    "origin_file_to_restore": str,
    # Sans effet pour un script : accepté, il ne sert pas.
    "restore_db_image_name": str,
}

_EXEC = {
    "run_test_exec": bool,
    "path_module_check": str,
    "generated_module": str,
    "tested_module": str,
    "generate_path": str,
    "search_class_module": str,
    "script_after_init_check": str,
    "init_module_name": str,
    "file_to_restore": str,
    "file_to_restore_origin": bool,
    "install_path": str,
    "run_in_sandbox": bool,
    "restore_db_image_name": str,
}

_OBLIGATOIRES = {
    "run_command": ("test_name", "script"),
    # Le scénario restaure toujours une base : son image doit être nommée,
    # une valeur par défaut désignerait l'image d'une autre version.
    "run_test_exec": (
        "test_name",
        "path_module_check",
        "restore_db_image_name",
    ),
}

# Ce que le pilote suppose d'une entrée qui ne le dit pas.
_DEFAUTS = {
    "sequence": 0,
    "disable": False,
    "run_in_sandbox": True,
    "file_to_restore_origin": False,
}

# Les noms de base de PostgreSQL : 63 octets au plus (NAMEDATALEN - 1).
LONGUEUR_NOM_BASE = 62


class SchemaInvalide(ValueError):
    """Le fichier de scénarios ne respecte pas le schéma ; le message
    nomme l'entrée fautive."""


def _nom_de_type(t):
    return {str: "texte", int: "entier", bool: "booléen"}[t]


def _type_ok(valeur, attendu):
    # bool est un int en Python : « sequence: true » serait accepté.
    if attendu is int:
        return isinstance(valeur, int) and not isinstance(valeur, bool)
    if attendu is str:
        return isinstance(valeur, str) and valeur.strip() != ""
    return isinstance(valeur, attendu)


def _valider_entree(rang, entree):
    if not isinstance(entree, dict):
        raise SchemaInvalide(f"entrée {rang} : un objet est attendu")
    nom = entree.get("test_name")
    qui = f"entrée {rang} « {nom} »" if nom else f"entrée {rang}"
    sortes = [s for s in ("run_command", "run_test_exec") if entree.get(s)]
    if len(sortes) != 1:
        raise SchemaInvalide(
            f"{qui} : exactement une sorte attendue, « run_command » ou"
            " « run_test_exec » à true"
        )
    sorte = sortes[0]
    permises = dict(
        _COMMUNES, **(_COMMANDE if sorte == "run_command" else _EXEC)
    )
    for cle, valeur in entree.items():
        if cle not in permises:
            raise SchemaInvalide(f"{qui} : clé inconnue « {cle} » ({sorte})")
        if not _type_ok(valeur, permises[cle]):
            raise SchemaInvalide(
                f"{qui} : « {cle} » doit être un"
                f" {_nom_de_type(permises[cle])} non vide"
            )
    for cle in _OBLIGATOIRES[sorte]:
        if cle not in entree:
            raise SchemaInvalide(f"{qui} : clé obligatoire « {cle} » absente")
    if entree.get("file_to_restore_origin") and not entree.get(
        "file_to_restore"
    ):
        raise SchemaInvalide(
            f"{qui} : « file_to_restore_origin » sans « file_to_restore »"
        )
    complete = dict(_DEFAUTS)
    complete.update(entree)
    complete["sorte"] = sorte
    return complete


def charger_et_valider(texte):
    """Les entrées du JSON `texte`, validées, valeurs par défaut posées et
    sorte notée sous « sorte ». Lève SchemaInvalide."""
    try:
        donnees = json.loads(texte)
    except ValueError as exc:
        raise SchemaInvalide(f"JSON illisible : {exc}") from None
    if not isinstance(donnees, dict):
        raise SchemaInvalide("un objet est attendu à la racine")
    inconnues = sorted(set(donnees) - {"lst_test"})
    if inconnues:
        raise SchemaInvalide(f"clé racine inconnue « {inconnues[0]} »")
    lst = donnees.get("lst_test")
    if not isinstance(lst, list) or not lst:
        raise SchemaInvalide("« lst_test » absente ou vide")
    entrees = [_valider_entree(rang, e) for rang, e in enumerate(lst)]
    vus = {}
    for rang, entree in enumerate(entrees):
        nom = entree["test_name"]
        if nom in vus:
            raise SchemaInvalide(
                f"entrée {rang} « {nom} » : nom déjà pris par l'entrée"
                f" {vus[nom]}"
            )
        vus[nom] = rang
    return entrees


def entree(entrees, nom):
    """L'entrée nommée `nom` ; KeyError sinon."""
    for e in entrees:
        if e["test_name"] == nom:
            return e
    raise KeyError(nom)


def _retenu(nom, motifs):
    """Le filtre de « -k » : sous-chaîne, ou motif fnmatch s'il porte un
    joker, comme « unittest -k »."""
    for motif in motifs:
        if any(c in motif for c in "*?["):
            if fnmatch.fnmatchcase(nom, motif):
                return True
        elif motif in nom:
            return True
    return False


def selectionner(entrees, motifs=(), noms=(), echecs=None):
    """Les entrées actives retenues, dans l'ordre du fichier.

    `noms` : noms exacts ; un nom inconnu ou désactivé lève ValueError.
    `motifs` : filtres de « -k ». `echecs` : un ensemble de noms (--failed).
    Les critères donnés s'additionnent ; sans aucun, toutes les actives."""
    actives = [e for e in entrees if not e["disable"]]
    tous = {e["test_name"]: e for e in entrees}
    for nom in noms:
        if nom not in tous:
            connus = ", ".join(sorted(e["test_name"] for e in actives))
            raise ValueError(f"scénario inconnu « {nom} » ; actifs : {connus}")
        if tous[nom]["disable"]:
            raise ValueError(f"scénario « {nom} » désactivé dans le JSON")
    if not (motifs or noms or echecs is not None):
        return actives
    return [
        e
        for e in actives
        if e["test_name"] in noms
        or (motifs and _retenu(e["test_name"], motifs))
        or (echecs is not None and e["test_name"] in echecs)
    ]


def elements(entrees):
    """Un lanceur.Element par entrée : nommé par le scénario, en phase
    `sequence`."""
    return [
        lanceur.Element(
            e["test_name"], phase=e["sequence"], nom=e["test_name"]
        )
        for e in entrees
    ]


def jobs_par_defaut(entrees):
    """Le nombre d'entrées de la phase la plus peuplée : toutes les
    entrées d'une phase partent ensemble."""
    par_phase = {}
    for e in entrees:
        par_phase[e["sequence"]] = par_phase.get(e["sequence"], 0) + 1
    return max(par_phase.values(), default=1)


def _csv(valeur):
    return [v for v in (valeur or "").strip().split(",") if v]


def chemins_origine(e):
    """Les chemins, relatifs à la racine du dépôt, que le scénario `e`
    modifie sur le dépôt d'ORIGINE et qu'une restauration git rétablit."""
    if e["sorte"] == "run_command":
        return [
            os.path.normpath(c) for c in _csv(e.get("origin_file_to_restore"))
        ]
    if e.get("file_to_restore_origin"):
        return [
            os.path.normpath(os.path.join(e["path_module_check"], c))
            for c in _csv(e.get("file_to_restore"))
        ]
    return []


def update_config(texte, depots, copies, module=None):
    """Le config.conf `texte` dont l'addons_path pointe sur les `copies`
    plutôt que sur les `depots` d'origine.

    Pour chaque dépôt, la PREMIÈRE entrée de l'addons_path qui finit par
    son chemin (sans « ./ » de tête) est retirée ; chaque copie est placée
    en tête, la dernière donnée en premier. Un chemin qui finit par
    `module` en perd ce dernier composant. Le texte rendu est celui
    qu'écrit configparser : commentaires perdus, clés gardées dans
    l'ordre."""
    lecteur = configparser.ConfigParser()
    lecteur.read_string(texte)
    lst_path = lecteur["options"]["addons_path"].strip(",").split(",")
    for cle in depots or ():
        if cle.startswith("./"):
            cle = cle[2:]
        if module and cle.endswith(module):
            cle = cle[: -(len(module) + 1)]
        for chemin in lst_path:
            if chemin.endswith(cle):
                lst_path.remove(chemin)
                break
    for chemin in copies or ():
        if module and chemin.endswith(module):
            chemin = chemin[: -(len(module) + 1)]
        lst_path.insert(0, chemin)
    lecteur["options"]["addons_path"] = ",".join(lst_path)
    sortie = io.StringIO()
    lecteur.write(sortie)
    return sortie.getvalue()


class CleHooksAbsente(ValueError):
    """hooks.py ne porte aucune affectation de path_module_generate."""


# Dans cet ordre : la forme commentée d'abord, la forme active contenant
# les deux autres.
CLES_HOOKS = (
    "# path_module_generate = ",
    "#path_module_generate = ",
    "path_module_generate = ",
)


def reecrire_hooks(source, bac, template=None):
    """Le hooks.py `source` d'un module générateur, réécrit pour générer
    dans `bac`.

    La première clé de CLES_HOOKS trouvée reçoit `"bac"` ; sa ligne et
    tout ce qui la suit jusqu'à la prochaine ligne vide sont remplacés. Avec
    `template` (par défaut : vrai si le hook calcule « template_dir =
    os.path.normpath »), une ligne `template_dir = "bac/" + MODULE_NAME` à
    la même indentation suit. Enfin « # path_module_generate = » et
    « # "path_sync_code": path_module_generate, » sont décommentés
    partout. Une transformation par chaînes, sans analyse du Python : un
    hooks.py qui s'écarte du gabarit du générateur se réécrit mal.

    Lève CleHooksAbsente si aucune clé n'est trouvée."""
    if template is None:
        template = "template_dir = os.path.normpath" in source
    trouvee = None
    for cle in CLES_HOOKS:
        if cle in source:
            trouvee = cle
            break
    if trouvee is None:
        raise CleHooksAbsente(f"aucune des clés {list(CLES_HOOKS)}")
    debut = source.find(trouvee)
    debut_ligne = source.rfind("\n", 0, debut) + 1
    indentation = debut - debut_ligne
    # Sans ligne vide après la clé, find rend -1 et la tranche [-1:] garde
    # le dernier caractère du fichier.
    fin = source.find("\n\n", debut)
    if template:
        nouveau = (
            source[: debut + len(trouvee)]
            + f'"{bac}"\n'
            + f"{indentation * ' '}template_dir ="
            f' "{bac}/" + MODULE_NAME\n\n' + source[fin:]
        )
    else:
        nouveau = source[: debut + len(trouvee)] + f'"{bac}"' + source[fin:]
    nouveau = nouveau.replace(
        "# path_module_generate = ", "path_module_generate = "
    )
    return nouveau.replace(
        '# "path_sync_code": path_module_generate,',
        '"path_sync_code": path_module_generate,',
    )


def nouveau_run_id():
    """L'identifiant d'un passage de campagne : 8 chiffres hexadécimaux."""
    return uuid.uuid4().hex[:8]


def prefixe_bases(run_id):
    """Le préfixe des bases du passage `run_id` : le démontage supprime
    celles-là, et aucune autre."""
    return f"test_scn_{run_id}_"


def nom_base(run_id, nom=None, alea=None):
    """Un nom de base unique du passage `run_id` :
    test_scn_<run_id>_<12 hex>[_<nom>], borné à LONGUEUR_NOM_BASE.

    Le nom du scénario, réduit à [a-z0-9_], ne sert qu'à le reconnaître
    dans la liste des bases ; il est tronqué le premier."""
    alea = alea or uuid.uuid4().hex[:12]
    base = prefixe_bases(run_id) + alea
    if nom:
        base += "_" + re.sub(r"[^a-z0-9_]", "_", nom.lower())
    return base[:LONGUEUR_NOM_BASE]


def lire_version(racine):
    """La version Odoo active (.odoo-version), sans fin de ligne."""
    with open(os.path.join(racine, ".odoo-version"), encoding="utf-8") as fh:
        return fh.readline().strip()


def json_par_defaut(racine, version):
    return os.path.join(
        racine, "script", "test", f"config_testcase.odoo{version}.json"
    )


def depots_du_generateur(version):
    """Les dépôts que les scénarios copient et contrôlent, relatifs à la
    racine : propres avant le passage, propres après."""
    return [
        f"./odoo{version}/addons/TechnoLibre_odoo-code-generator-template",
        f"./odoo{version}/addons/OCA_server-tools",
    ]
