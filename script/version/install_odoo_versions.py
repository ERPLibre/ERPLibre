#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Installe une liste de versions d'Odoo, l'une après l'autre.

Le même chemin sert à TODO › Installation, qu'on y choisisse plusieurs
versions ou « w », et à « make install_odoo_all_version » : installer toutes
les versions, c'est installer la liste entière du catalogue.

    install_odoo_versions.py 18.0 12.0          # dans cet ordre
    install_odoo_versions.py --all [--with_extra]

Un échec n'arrête pas le lot : chaque version est tentée, puis un bilan donne
la réussite ou le code de retour de chacune. Chaque installation rend sa
version active ; à la fin, la version active avant le lot le redevient si son
Odoo est encore installé, sinon la dernière installée sans erreur le reste.
EL_FREEZE, s'il est posé, atteint chaque installation par l'environnement.
"""

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from script.todo.version_manager import get_odoo_version  # noqa: E402

FICHIER_ACTIVE = ".erplibre-version"


def commande_installation(erplibre_version, avec_extra=False):
    """La commande qui installe une version d'ERPLibre, comme ses cibles
    « make install_odoo_<N> »."""
    cmd = (
        "./script/version/update_env_version.py"
        f" --erplibre_version {erplibre_version} --install_dev"
    )
    return cmd + " --with_extra" if avec_extra else cmd


def commande_bascule(erplibre_version):
    """La commande qui rend une version d'ERPLibre déjà installée active."""
    return (
        "./script/version/update_env_version.py"
        f" --erplibre_version {erplibre_version} --switch"
    )


def postgresql_minimum(entrees):
    """Le PostgreSQL majeur qu'exigent ensemble des entrées du catalogue.

    Chaque entrée peut porter « postgresql_version », le majeur minimum de sa
    version d'Odoo. Rend le plus grand en entier, ou None si aucune n'en
    porte : l'installeur garde alors son propre choix.
    """
    requis = [
        int(entree["postgresql_version"])
        for entree in entrees
        if entree.get("postgresql_version")
    ]
    return max(requis) if requis else None


def ordre_tout(entrees):
    """Toutes les versions, de la plus récente à la plus ancienne, la version
    par défaut en dernier : sur une machine neuve, sans version active avant
    le lot, c'est elle qui reste active."""
    recentes = sorted(
        entrees,
        key=lambda e: [int(x) for x in e["odoo_version"].split(".")],
        reverse=True,
    )
    return [e for e in recentes if not e.get("default")] + [
        e for e in recentes if e.get("default")
    ]


def cible_retour(active_avant, reussies, installees, active):
    """La version d'ERPLibre à rendre active après le lot, ou None.

    `active_avant` : la version active avant le lot ; `reussies` : les
    versions installées sans erreur, dans l'ordre ; `installees` : les Odoo
    installés après le lot (« odoo18.0 ») ; `active` : la version active
    maintenant. None quand la cible est déjà active ou qu'aucune ne convient.
    """
    odoo_avant = (active_avant or "").split("_python", 1)[0]
    if odoo_avant and odoo_avant in installees:
        cible = active_avant
    elif reussies:
        cible = reussies[-1]
    else:
        return None
    return None if cible == active else cible


def installer_lot(
    entrees,
    commandes,
    lancer,
    active,
    marquer,
    t=str,
    active_avant=None,
    installees=None,
):
    """Lance `commandes[i]`, qui installe `entrees[i]`, dans l'ordre.

    `lancer(cmd)` exécute une commande shell et rend son code de retour ;
    `active()` rend la version d'ERPLibre active ; `marquer(version)` inscrit
    une version comme courante après une bascule ; `t` traduit les messages.
    `active_avant` : la version à retrouver, lue par l'appelant quand une
    étape antérieure peut la changer ; à défaut, la version active au départ.
    `installees()` rend les Odoo installés (« odoo18.0 ») ; à défaut, ceux
    du catalogue. Rend 0 si toutes ont réussi, 1 sinon.
    """
    if active_avant is None:
        active_avant = active()
    bilan = []
    for rang, (entree, cmd) in enumerate(zip(entrees, commandes), start=1):
        print(
            f"\n▶ Odoo {entree.get('odoo_version')} ({rang}/{len(commandes)})"
        )
        print(f"{t('Will execute:')}\n{cmd}")
        bilan.append((entree, lancer(cmd)))

    reussies = [e.get("erplibre_version") for e, code in bilan if code == 0]
    installees = installees or (lambda: get_odoo_version()[1])
    cible = cible_retour(active_avant, reussies, installees(), active())
    if cible:
        print(f"\n{t('Switching back to:')} {cible}")
        lancer(commande_bascule(cible))
        marquer(active())

    print(f"\n📋 {t('Installation summary:')}")
    for entree, code in bilan:
        if code == 0:
            print(f"✅ Odoo {entree.get('odoo_version')}")
        else:
            print(
                f"❌ Odoo {entree.get('odoo_version')} —"
                f" {t('The Bash script failed with return code')} {code}."
            )
    print(f"ℹ️  {t('Active version:')} {active()}")
    if len(reussies) < len(bilan):
        print("Wait after installation and open projects by terminal.")
        print("make open_terminal")
        return 1
    return 0


def _active():
    try:
        with open(FICHIER_ACTIVE) as fichier:
            return fichier.read().strip()
    except OSError:
        return ""


def _marquer(erplibre_version):
    if not erplibre_version:
        return
    from script.version import erplibre_state

    odoo = erplibre_version.split("_python", 1)[0]
    erplibre_state.set_version_switched(odoo[len("odoo") :])


def _lancer(cmd):
    return subprocess.run(cmd, shell=True, executable="/bin/bash").returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "versions",
        nargs="*",
        help="Versions d'Odoo (« 18.0 ») ou d'ERPLibre, dans l'ordre voulu.",
    )
    parser.add_argument(
        "--all", action="store_true", help="Toutes les versions du catalogue."
    )
    parser.add_argument(
        "--with_extra", action="store_true", help="Avec les modules extra."
    )
    args = parser.parse_args(argv)
    catalogue = get_odoo_version()[0]
    if args.all == bool(args.versions):
        parser.error("donner des versions, ou --all, mais pas les deux")
    if args.all:
        entrees = ordre_tout(catalogue)
    else:
        par_nom = {}
        for entree in catalogue:
            par_nom[entree["odoo_version"]] = entree
            par_nom[entree["erplibre_version"]] = entree
        inconnues = [v for v in args.versions if v not in par_nom]
        if inconnues:
            parser.error(f"version inconnue : {', '.join(inconnues)}")
        entrees = [par_nom[v] for v in args.versions]
    commandes = [
        commande_installation(e["erplibre_version"], args.with_extra)
        for e in entrees
    ]
    return installer_lot(entrees, commandes, _lancer, _active, _marquer)


if __name__ == "__main__":
    sys.exit(main())
