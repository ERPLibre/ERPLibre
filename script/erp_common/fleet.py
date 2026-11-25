# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Retrait d'une instance : des étapes rejouables, puis l'entrée du registre.

L'ERP fournit la liste des étapes ; remove les joue toutes, note celles qui
échouent sans s'arrêter, et ne retire l'entrée du registre
private/<erp>/instances.json que lorsque toutes ont réussi. Chaque étape
est rejouable (IF EXISTS, -f, rm -rf) et une commande qui répond que
l'objet n'existe plus compte comme réussie : un retrait interrompu se
relance.
"""

import json
import os
import shutil

from script.erp_common import instances
from script.erp_common.steps import t

# Ce que répond une commande sur un objet déjà parti : le retrait est fait.
GONE = ("no such", "not found", "does not exist", "unknown")


class Step:
    """Une commande, ou une action locale décrite pour l'essai à blanc."""

    def __init__(self, argv=None, describe=None, action=None):
        self.argv, self.describe, self.action = argv, describe, action

    def text(self):
        return " ".join(self.argv) if self.argv else self.describe


def drop_database(entry, sudo_mariadb):
    """Étapes qui suppriment la base `entry["db_name"]` et son compte.

    MariaDB (défaut de `entry["db"]`) passe par `sudo_mariadb`, argv du
    client lancé en administrateur ; PostgreSQL par dropdb et dropuser
    sous le compte postgres.
    """
    db = entry["db_name"]
    if entry.get("db", "mariadb") == "mariadb":
        return [
            Step(
                sudo_mariadb
                + [
                    "-e",
                    f"DROP DATABASE IF EXISTS {db};"
                    f" DROP USER IF EXISTS '{db}'@'localhost';",
                ]
            )
        ]
    pg = ["sudo", "-u", "postgres"]
    return [
        Step(pg + ["dropdb", "--if-exists", db]),
        Step(pg + ["dropuser", "--if-exists", db]),
    ]


def remove_tree(path):
    """Étape locale : `path` et son contenu partent, absent ou pas."""
    return Step(
        describe=f"rm -rf {path}",
        action=lambda: shutil.rmtree(path, ignore_errors=True),
    )


def remove_file(path):
    """Étape locale : le fichier `path` part, absent ou pas."""

    def action():
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    return Step(describe=f"rm -f {path}", action=action)


def remove(erp, name, entry, confirm, dry_run, system, root, plan):
    """Retire l'instance `name` de `erp` ; rend 0, 1 (une étape a échoué)
    ou 2 (non confirmé).

    `plan(name, entry, system, root)` rend (étapes, avis) : l'avis, s'il
    n'est pas vide, s'affiche après les étapes. `system.run(argv)` rend
    (code, sortie). Rien ne part sans `confirm` égal à `name` ; `dry_run`
    affiche chaque étape sans rien lancer ni toucher au registre.
    """
    if not dry_run and confirm != name:
        print(t("Removing deletes %s: retype its name with --confirm.") % name)
        return 2
    steps, notice = plan(name, entry, system, root)
    failed = []
    for step in steps:
        if dry_run:
            print(f"  [dry-run] {step.text()}")
            continue
        if step.action:
            try:
                step.action()
            except OSError as e:
                failed.append(f"{step.text()} — {e}")
            continue
        code, out = system.run(step.argv)
        if code and not any(g in out.lower() for g in GONE):
            failed.append(f"{step.text()} — {out.strip()[-300:]}")
    if notice:
        print(notice)
    if dry_run:
        return 0
    if failed:
        print(
            t("Not everything was removed; running the removal again resumes:")
        )
        for line in failed:
            print(f"  ✗ {line}")
        return 1
    registry = os.path.join(root, instances.registry_path(erp))
    known = instances.load_registry(erp, root)
    known.pop(name, None)
    with open(registry, "w", encoding="utf-8") as f:
        f.write(
            json.dumps({"instances": known}, indent=4, sort_keys=True) + "\n"
        )
    print(t("Instance %s removed.") % name)
    return 0
