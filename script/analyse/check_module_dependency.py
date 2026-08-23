#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les modules d'une base et ce qui les relie.

`check_module_package` répond « quels modules manquent ». La question
d'à côté reste sans réponse : « celui-ci, puis-je le retirer, et
qu'entraîne-t-il avec lui ». On l'a payé cher au palier 17 → 18 —
`web_responsive` devenu incompatible avec `muk_web_theme` — où il a fallu
écrire la requête à la main pour savoir si quelqu'un en dépendait.

Quatre relations, et non une seule liste :

  ce dont il dépend      ce qu'il faut installer AVANT lui
  ce qui en dépend       ce qui casse si on le retire
  ce qu'il entraîne      la fermeture avale, dépendances des dépendances
  ce qui tombe avec lui  la fermeture amont

La lecture n'écrit jamais : `check_module_package.run_psql` ouvre la
session en lecture seule côté SERVEUR, pas côté politesse.
"""

import json
import os
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.analyse import check_module_package as package  # noqa: E402

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


# Un graphe de modules Odoo est peu profond — `base` est à la racine et la
# plus longue chaîne réelle tient en une dizaine de sauts. La borne existe
# pour qu'un cycle en base, qui NE DEVRAIT pas exister, produise un
# résultat faux et visible plutôt qu'une boucle sans fin.
PROFONDEUR_MAX = 64

FILTRES = ("all", "installed", "absent", "broken")

# Ce qui compte comme « en place ». « to upgrade » l'est : le module est
# chargé, il sera seulement rejoué. « to install » ne l'est pas encore.
ETATS_PRESENTS = ("installed", "to upgrade")


def reverse(depend):
    """{module: [ce qui dépend de lui]} à partir de {module: [dépendances]}.

    Les modules cités comme dépendance mais absents de la base ont eux
    aussi leur entrée : c'est précisément le cas qu'on cherche à voir.
    """
    inverse = {}
    for module, lst in depend.items():
        inverse.setdefault(module, [])
        for nom in lst:
            inverse.setdefault(nom, []).append(module)
    return {nom: sorted(set(lst)) for nom, lst in inverse.items()}


def closure(nom, graphe):
    """Tout ce que `nom` atteint dans `graphe`, lui-même exclu.

    En largeur et non en profondeur : la récursion sur un graphe cyclique
    déborde la pile avant qu'on ait compris pourquoi.
    """
    vus, bord, profondeur = set(), [nom], 0
    while bord and profondeur < PROFONDEUR_MAX:
        suivant = []
        for courant in bord:
            for voisin in graphe.get(courant, []):
                if voisin not in vus and voisin != nom:
                    vus.add(voisin)
                    suivant.append(voisin)
        bord = suivant
        profondeur += 1
    return sorted(vus)


def present(etat):
    return etat in ETATS_PRESENTS


def broken(recensement, depend):
    """[(module, dépendance, raison)] — ce qui est installé sur du vide.

    Un module installé dont une dépendance ne l'est pas est un état
    qu'Odoo ne produit jamais lui-même ; il vient d'une migration, d'une
    désinstallation forcée ou d'un addons-path incomplet. Le charger
    échoue, ou pire, réussit à moitié.
    """
    lst = []
    for module, infos in sorted(recensement.items()):
        if not present(infos[0]):
            continue
        for nom in sorted(set(depend.get(module, []))):
            if nom not in recensement:
                lst.append((module, nom, "unknown"))
            elif not present(recensement[nom][0]):
                lst.append((module, nom, recensement[nom][0]))
    return lst


def survey(database):
    """Tout ce que l'écran et le rapport ont besoin de savoir.

    Une seule lecture de la base pour les deux : deux assemblages
    finiraient par montrer deux états contradictoires du même système.
    """
    recensement = package.census(database)
    if recensement is None:
        return {"database": database, "unavailable": True}
    depend = package.dependencies(database)
    # Un module sans dépendance déclarée doit exister dans le graphe :
    # sinon `closure` et l'écran le traitent comme inconnu.
    depend = {nom: sorted(set(depend.get(nom, []))) for nom in recensement}
    return {
        "database": database,
        "version": package.db_version(database),
        "modules": recensement,
        "depends": depend,
        "dependents": reverse(depend),
        "broken": broken(recensement, depend),
    }


def verdict(rapport, nom):
    infos = rapport["modules"].get(nom)
    if infos is None:
        return "unknown"
    return package.ETAT_VERS_VERDICT.get(infos[0], "uninstallable")


def icon(rapport, nom):
    return package.ICONE.get(verdict(rapport, nom), "·")


def counts(rapport, nom):
    """(dépendances, dépendants, dépendants EN PLACE).

    Le troisième chiffre est celui qui décide d'un retrait. Sur une base
    réelle, `web_responsive` a deux dépendants déclarés et zéro installé :
    ne montrer que « 2 » ferait renoncer à un retrait sans danger.
    """
    aval = rapport["dependents"].get(nom, [])
    return (
        len(rapport["depends"].get(nom, [])),
        len(aval),
        sum(1 for autre in aval if present_of(rapport, autre)),
    )


def modules_cassants(rapport):
    """Les modules qui apparaissent à gauche d'une dépendance cassée."""
    return {module for module, _dep, _raison in rapport.get("broken", [])}


def rows(rapport, filtre="all"):
    """La liste de gauche : un module par ligne, déjà triée.

    Tri par nom. Trier par nombre de dépendants mettrait `base` en tête à
    chaque fois — vrai, et sans intérêt : on cherche un module qu'on
    nomme, pas le plus populaire.
    """
    cassants = modules_cassants(rapport)
    lst = []
    for nom in sorted(rapport["modules"]):
        etat = rapport["modules"][nom][0]
        if filtre == "installed" and not present(etat):
            continue
        if filtre == "absent" and present(etat):
            continue
        if filtre == "broken" and nom not in cassants:
            continue
        amont, aval, vivants = counts(rapport, nom)
        lst.append(
            {
                "name": nom,
                "label": f"{icon(rapport, nom)} {nom}",
                "detail": f"{amont}↓ {vivants}/{aval}↑",
                "broken": nom in cassants,
            }
        )
    return lst


DETAILS = ("depends", "dependents", "pulls", "falls")

TITRE_DETAIL = {
    "depends": "What it needs, directly",
    "dependents": "What needs it, directly",
    "pulls": "Everything it pulls in",
    "falls": "Everything that falls with it",
}


def listing(rapport, nom, mode):
    """Les noms à montrer pour ce mode, dans l'ordre d'affichage."""
    if mode == "depends":
        return rapport["depends"].get(nom, [])
    if mode == "dependents":
        return rapport["dependents"].get(nom, [])
    if mode == "pulls":
        return closure(nom, rapport["depends"])
    if mode == "falls":
        return closure(nom, rapport["dependents"])
    return []


def paint(texte, genre, colour):
    from script.todo import migration_status as status

    return status.paint(texte, genre, colour)


def pane_text(rapport, nom, mode=None, colour=False, limit=0):
    """Le panneau de droite pour le module choisi."""
    if not nom:
        return t("Nothing to show yet.")
    infos = rapport["modules"].get(nom)
    if infos is None:
        return f"❌ {nom} : {t('unknown to this database')}"
    etat, resume, application, auteur = infos
    lignes = [
        paint(f"{icon(rapport, nom)} {nom}", "step", colour),
        f"   {resume or ''}".rstrip(),
        "",
        f"   {t('state'):<22} {etat}",
        f"   {t('author'):<22} {auteur or '—'}",
        f"   {t('application'):<22} {t('yes') if application else t('no')}",
    ]
    amont, aval, vivants = counts(rapport, nom)
    lignes += [
        f"   {t('depends on'):<22} {amont}",
        f"   {t('needed by'):<22} {aval}"
        f"   ·  {vivants} {t('of them installed')}",
    ]
    if present(etat) and aval and not vivants:
        # La réponse à « puis-je le retirer », écrite plutôt que déduite
        # de deux chiffres qu'il faudrait comparer soi-même.
        lignes.append(
            "   " + paint(t("nothing installed depends on it"), "ok", colour)
        )
    lignes.append("")
    if mode in DETAILS:
        lst = listing(rapport, nom, mode)
        lignes.append(paint(f"   {t(TITRE_DETAIL[mode])}", "step", colour))
        if not lst:
            lignes.append(f"      {t('nothing')}")
        for autre in lst[: limit or None]:
            marque = "" if present_of(rapport, autre) else f"  ← {t('absent')}"
            genre = "ok" if present_of(rapport, autre) else "warn"
            lignes.append(
                f"      {icon(rapport, autre)} "
                + paint(f"{autre}{marque}", genre, colour)
            )
        if limit and len(lst) > limit:
            lignes.append(f"      … {len(lst) - limit} {t('more')}")
    else:
        lignes.append(f"   {t('press d to walk the dependencies')}")
    casses = [
        (dep, raison)
        for module, dep, raison in rapport.get("broken", [])
        if module == nom
    ]
    if casses:
        lignes.append("")
        lignes.append(
            paint(
                f"   ❌ {t('installed on missing dependencies')}",
                "fail",
                colour,
            )
        )
        for dep, raison in casses:
            lignes.append(f"      {dep} ({raison})")
    return "\n".join(lignes)


def present_of(rapport, nom):
    infos = rapport["modules"].get(nom)
    return bool(infos) and present(infos[0])


def head_text(rapport):
    installes = sum(
        1 for infos in rapport["modules"].values() if present(infos[0])
    )
    total = len(rapport["modules"])
    casses = len(rapport.get("broken", []))
    texte = (
        f"📦 {rapport['database']}"
        f"  ({t('Odoo')} {rapport.get('version') or '?'})"
        f"  ·  {installes}/{total} {t('modules installed')}"
    )
    if casses:
        texte += f"  ·  ❌ {casses} {t('broken dependency(ies)')}"
    return texte


def render_text(rapport, limit=0, cap=0):
    """Le rapport en clair, pour un terminal qui n'ouvre pas d'écran.

    `cap` borne le NOMBRE DE MODULES, `limit` la longueur de chaque liste
    de dépendances. Une base porte trois mille modules : sans borne, le
    repli déverse six mille lignes dans un menu, ce qui n'est pas un
    repli mais une seconde panne.
    """
    if rapport.get("unavailable"):
        return [f"❌ {t('Cannot read the database: ')}{rapport['database']}"]
    lignes = [head_text(rapport), ""]
    lst_row = rows(rapport)
    for row in lst_row[: cap or None]:
        nom = row["name"]
        amont = rapport["depends"].get(nom, [])
        lignes.append(f"{row['label']:<44} {row['detail']}")
        if amont:
            lignes.append(f"      → {', '.join(amont[: limit or None])}")
    if cap and len(lst_row) > cap:
        lignes.append(f"   … {len(lst_row) - cap} {t('more')}")
    if rapport.get("broken"):
        lignes.append("")
        lignes.append(f"❌ {t('installed on missing dependencies')}")
        for module, dep, raison in rapport["broken"]:
            lignes.append(f"   {module} → {dep} ({raison})")
    return lignes


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "List every module of a database and how they depend on one"
            " another. Read-only."
        )
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument(
        "--limit", type=int, default=0, help="cap long lists (0 = no cap)"
    )
    parser.add_argument("--json", action="store_true", help="machine output")
    parser.add_argument(
        "--no-tui", action="store_true", help="never open the screen"
    )
    config = parser.parse_args(argv)

    rapport = survey(config.database)
    if rapport.get("unavailable"):
        print(f"❌ {t('Cannot read the database: ')}{config.database}")
        return 2
    if config.json:
        print(
            json.dumps(rapport, indent=2, sort_keys=True, ensure_ascii=False)
        )
        return 1 if rapport["broken"] else 0
    if not config.no_tui:
        try:
            from script.analyse.check_module_dependency_tui import run_tui
        except Exception:
            run_tui = None
        if run_tui and run_tui(rapport):
            return 1 if rapport["broken"] else 0
    print("\n".join(render_text(rapport, limit=config.limit)))
    return 1 if rapport["broken"] else 0


if __name__ == "__main__":
    sys.exit(main())
