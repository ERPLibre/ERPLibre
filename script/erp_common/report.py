# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Bilan de santé d'une instance : résultats ok, warn ou fail, et leur
affichage.

Une vérification rend un Result(key, level, detail) : `key` nomme la
vérification et choisit son libellé dans le dictionnaire que l'ERP fournit,
`level` vaut ok, warn ou fail, `detail` dit ce qui fonde le verdict. Un
seul fail suffit pour que le bilan échoue ; un warn se lit sans échouer.
"""

import collections

from script.erp_common.steps import t

Result = collections.namedtuple("Result", "key level detail")

LEVELS = ("ok", "warn", "fail")
MARKS = {"ok": "✓", "warn": "!", "fail": "✗"}

# Libellés (clés i18n) des vérifications que ce module définit ; un ERP
# les fusionne aux siens.
LABELS = {"pin": "Pin"}


def check_pin(entry, pin):
    """L'instance est-elle au commit (à l'image) épinglé ? Après une montée
    revenue en arrière, rien d'autre ne dit qu'elle est en retard.

    En conteneurs, compare `image` de l'entrée à `docker_image` de
    l'épinglage et affiche leur dernier segment (40 caractères au plus) ;
    sinon compare les `commit` et affiche leurs sept premiers caractères.
    """
    if entry.get("runtime") == "container":
        have, want = entry.get("image", ""), pin.get("docker_image", "")
        shown = (have.rsplit("/", 1)[-1][:40], want.rsplit("/", 1)[-1][:40])
    else:
        have, want = entry.get("commit", ""), pin.get("commit", "")
        shown = (have[:7] or "?", want[:7])
    if have != want:
        return Result(
            "pin", "warn", t("at %s, pinned at %s: upgrade it") % shown
        )
    return Result("pin", "ok", shown[1])


def line(result, labels):
    """« <marque> <libellé traduit>: <détail> », indenté de deux espaces."""
    return f"  {MARKS[result.level]} {t(labels[result.key])}: {result.detail}"


def show(results, labels, out=print):
    """Affiche une ligne par résultat ; vrai si l'un d'eux est un fail."""
    failed = False
    for r in results:
        out(line(r, labels))
        failed = failed or r.level == "fail"
    return failed
