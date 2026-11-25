# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les ERP hors Odoo dont Google Repo récupère la source.

`ERP_SOURCES` associe le nom d'un ERP à une `Source`, dont les chemins
sont relatifs à la racine du dépôt :
- `checkout` : le dossier où « repo sync » pose la source. Sa seule
  présence ajoute le fragment de l'ERP à la fusion des manifestes : un
  projet sorti de la fusion est effacé par le prochain « repo sync »,
  fichiers ignorés compris ;
- `conf` : la liste CSV des manifestes que la fusion lit pour cet ERP ;
- `manifest` : le fragment qui épingle le projet de l'ERP, cité par `conf`
  et dont le projet a `checkout` pour chemin.

`label` est le nom que l'aide de `--with_<erp>` affiche.

La fusion (`git_merge_repo_manifest`) tire de cette table un drapeau
`--with_<erp>` par ERP et le fragment ajouté d'office quand le checkout
existe ; `repo_pull` en tire les dossiers que sa prédiction recrée. L'ordre
de la table est celui de la fusion.
"""

import collections
import os

Source = collections.namedtuple(
    "Source", ("label", "checkout", "conf", "manifest")
)

ERP_SOURCES = {
    "dolibarr": Source(
        label="Dolibarr",
        checkout=os.path.join("dolibarr", "dolibarr"),
        conf=os.path.join("conf", "git_manifest_dolibarr.csv"),
        manifest=os.path.join("manifest", "git_manifest_dolibarr.xml"),
    ),
}


def flag(erp):
    """Le nom d'attribut argparse du drapeau `--with_<erp>`."""
    return f"with_{erp}"


def checkouts():
    """Les dossiers de checkout de la table, dans son ordre."""
    return tuple(source.checkout for source in ERP_SOURCES.values())


def present(racine=""):
    """Les ERP de la table dont le checkout existe sous `racine` (le dossier
    courant par défaut), dans l'ordre de la table."""
    return [
        erp
        for erp, source in ERP_SOURCES.items()
        if os.path.isdir(os.path.join(racine, source.checkout))
    ]
