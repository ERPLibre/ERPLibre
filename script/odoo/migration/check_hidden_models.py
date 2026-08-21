#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les modèles qui ont des données que PLUS PERSONNE ne peut voir.

D'où vient ce test
------------------
Après une migration 12 → 18, les documents DMS avaient « disparu ». Ils
n'avaient pas disparu : 69 fichiers et 23 Mo étaient intacts en base. Ce
qui avait changé, c'est le modèle de sécurité — OCA DMS pose une règle
GLOBALE sur une permission accordée par un `dms.access.group`, et la
conversion depuis MuK n'en avait créé aucun, faute d'équivalent à
convertir.

Rien ne pouvait le voir venir. Les comptages de lignes disaient « tout est
là », et c'était vrai. Le test de fumée ouvrait des pages publiques, et
elles répondaient. Le trou est exactement entre les deux : des données
présentes, et une règle qui les masque intégralement.

Ce qu'on cherche
----------------
Un modèle tel que : il a des lignes, il porte au moins une règle GLOBALE,
et AUCUN utilisateur interne actif n'en voit une seule. « Aucun » est le
mot important — un modèle que seul un comptable voit est normal ; un
modèle que personne ne voit est soit une refonte de sécurité ratée, soit
des données devenues inatteignables.

Pourquoi pas en SQL
-------------------
Une règle est un domaine Odoo, parfois avec `user.`, `company_ids`, ou un
champ calculé cherchable — `permission_read` de DMS en est un, et il
déclenche une sous-requête que rien dans `ir_rule` ne laisse deviner. Il
faut l'ORM pour l'évaluer, donc le shell.

Le super-utilisateur est exclu : les règles ne s'appliquent pas à lui, et
un comptage fait en son nom déclarerait saine une base muette. C'est
précisément l'erreur qui aurait laissé passer le cas DMS.

Codes de sortie : 0 rien à signaler, 1 des trouvailles, 2 l'outil a échoué.
"""

import argparse
import os
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

from script.odoo.migration import database_cleanup  # noqa: E402

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


DEBUT = database_cleanup.START
FIN = database_cleanup.END

# Ces modèles sont invisibles PAR DESSEIN : ils portent des règles globales
# et ne s'adressent à personne en particulier. Les signaler à chaque
# migration noierait la vraie trouvaille sous le bruit, et un rapport
# qu'on apprend à ignorer ne sert plus à rien.
ATTENDUS = (
    "ir.rule",
    "ir.model.access",
    "res.users.log",
    "bus.bus",
    "bus.presence",
    "mail.notification",
    "ir.logging",
    "ir.autovacuum",
)

SCRIPT = """
import json
LIMITE = {limite}
ATTENDUS = set({attendus!r})
rapport = {{"models": [], "checked": 0, "users": []}}
try:
    # Les utilisateurs INTERNES actifs, sans le super-utilisateur : les
    # règles ne s'appliquent pas à lui, et compter en son nom
    # déclarerait saine une base que personne ne peut lire.
    membres = env["res.users"].sudo().search([
        ("active", "=", True),
        ("id", "!=", 1),
        ("share", "=", False),
    ], limit=LIMITE)
    rapport["users"] = membres.mapped("login")
    if not membres:
        rapport["no_user"] = True
    else:
        vus = set(
            env["ir.rule"].sudo()
            .search([("global", "=", True), ("active", "=", True)])
            .mapped("model_id.model")
        )
        for nom in sorted(vus - ATTENDUS):
            modele = env.get(nom)
            if modele is None or modele._abstract or modele._transient:
                continue
            try:
                total = modele.sudo().search_count([])
            except Exception:
                continue
            if not total:
                continue
            rapport["checked"] += 1
            # Court-circuit : dès qu'UN utilisateur voit une ligne, le
            # modèle n'est pas muet. Inutile d'interroger les autres.
            visible = False
            for membre in membres:
                try:
                    if modele.with_user(membre).search([], limit=1):
                        visible = True
                        break
                except Exception:
                    # Un refus d'accès n'est pas une ligne visible.
                    continue
            if not visible:
                rapport["models"].append({{"model": nom, "rows": total}})
except Exception as exc:
    rapport["error"] = "%s: %s" % (type(exc).__name__, exc)
print({debut!r})
print(json.dumps(rapport))
print({fin!r})
"""


def build_script(limite=25):
    return SCRIPT.format(
        limite=limite, attendus=list(ATTENDUS), debut=DEBUT, fin=FIN
    )


def render(rapport):
    if rapport.get("no_user"):
        return [f"⚠ {t('No internal user to test visibility with.')}"]
    muets = rapport.get("models") or []
    lignes = [
        f"🔍 {rapport.get('checked', 0)}"
        f" {t('model(s) with a global rule and some data,')}"
        f" {t('checked against')} {len(rapport.get('users') or [])}"
        f" {t('internal user(s)')}"
    ]
    if not muets:
        lignes.append(f"   ✅ {t('Every one of them is visible to someone.')}")
        return lignes
    lignes.append(
        f"   ❌ {len(muets)} {t('model(s) nobody can see a single row of')} :"
    )
    for entree in sorted(muets, key=lambda item: -item["rows"]):
        lignes.append(
            f"       {entree['model']:<38} {entree['rows']:>8}"
            f" {t('row(s)')}"
        )
    lignes.append(
        f"   {t('The data is there; a global rule hides all of it.')}"
    )
    return lignes


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Report models that hold data no internal user can see,"
            " because a global record rule filters every row out."
        )
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument("-c", "--config", default="config.conf")
    parser.add_argument(
        "--users",
        type=int,
        default=25,
        help="how many internal users to test with (default: 25)",
    )
    config = parser.parse_args(argv)

    souci = database_cleanup.require_matching_version(config.database)
    if souci:
        print(f"❌ {souci}")
        return 2
    try:
        rapport = database_cleanup.run_shell(
            config.database,
            config.config,
            build_script(config.users),
            echo=lambda texte: print(f"⧖ {texte}", flush=True),
        )
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return 2
    if rapport.get("error"):
        print(f"❌ {rapport['error']}")
        return 2
    print("\n".join(render(rapport)))
    return 1 if rapport.get("models") else 0


if __name__ == "__main__":
    sys.exit(main())
