#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Intégrité d'un code Dolibarr exporté, contre son commit épinglé.

La production pose le code par `git archive` du commit épinglé : la
référence est donc cette archive même, relue en flux et jamais extraite.
Chaque membre donne son empreinte git (sha1 de « blob <taille>\\0<contenu> »),
à laquelle se compare celle du fichier installé. export-ignore et
export-subst de .gitattributes sont appliqués par git, comme à
l'installation : rien d'écarté n'est « absent », rien de réécrit n'est
« modifié ».

Écarts : modified (contenu changé), missing, added (présent, inconnu de
l'archive), unreadable. conf/conf.php et install.lock, posés par
l'installation, ne comptent pas. Les dossiers de custom/ sont des modules,
listés à part ; les fichiers que Dolibarr livre à sa racine se vérifient.

La mécanique vient de script/erp_common/integrity ; ce module la lie aux
chemins de Dolibarr.
"""

from script.erp_common import integrity as common_integrity
from script.erp_common.integrity import (  # noqa: F401
    IntegrityError,
    archive_blobs,
    blob_hash,
)

# Posés par l'installation, jamais dans le dépôt.
_INSTALLED = {"htdocs/conf/conf.php", "htdocs/install.lock"}
_CUSTOM = "htdocs/custom/"


def compare_tree(code_root, blobs):
    """Les écarts entre `code_root` et les blobs du commit, triés.

    common_integrity.compare_tree lié aux fichiers que pose l'installation
    de Dolibarr (_INSTALLED) et à son dossier de modules (_CUSTOM).
    """
    return common_integrity.compare_tree(
        code_root, blobs, installed=_INSTALLED, custom=_CUSTOM
    )
