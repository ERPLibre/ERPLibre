#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les copies de site web qui ne savent plus se rendre après une montée.

`check_cow_views` prédit UN mode de rupture : la FORME que l'arch doit
avoir change entre deux versions — template autonome d'un côté, spec
d'héritage de l'autre. C'est celui qui arrête la migration elle-même, et
c'est pour cela qu'on le cherche AVANT de partir.

Deux autres modes la laissent finir sans un mot et n'apparaissent qu'à
l'ouverture de la page. Mesurés sur une migration 12 → 18 réelle :

  ancrage manquant   une vue héritière cherche `//t[@t-set='x']` dans la
                     copie. Le module a gagné cet ancrage en chemin — ici
                     au palier 14 → 15 — et sa propre vue héritière a
                     suivi ; la copie, elle, n'est jamais réécrite,
                     c'est une page d'utilisateur. Quatre paliers plus
                     tard /contact rendait 500, et rien ne l'avait dit.

  t-call pendant     la copie appelle un gabarit que la version cible ne
                     livre plus. `website.company_description` a disparu
                     en 18 : les deux copies qui l'appelaient rendaient
                     500, l'une d'elles pour CETTE raison seulement une
                     fois son ancrage remis.

Le premier se répare : l'ancrage existe dans la vue module de même clé,
on le remet là où le module le place. Le second ne se répare pas — un
gabarit disparu ne se réinvente pas — on retire l'appel, et la personne
décide si le bloc doit revenir autrement.

Lecture seule par défaut. `--apply` écrit, puis RELIT pour vérifier :
annoncer « corrigé » sans regarder ferait rouvrir la même page cassée.
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


def run_psql(database, sql, read_only=True):
    """Interroger la base. None si elle ne répond pas.

    Lecture seule garantie par le SERVEUR et non par la politesse du
    code : une réparation qui se trompe de base doit être refusée par
    PostgreSQL, pas par une relecture attentive.
    """
    # PGOPTIONS et non un « SET » en tête : celui-ci ÉCRIT une ligne
    # « SET » dans la sortie, que le json.loads d'à côté prend en pleine
    # figure. Même forme que fix_view_type.py, pour la même raison.
    env = os.environ.copy()
    if read_only:
        env["PGOPTIONS"] = "-c default_transaction_read_only=on"
    env["PSQLRC"] = ""
    result = subprocess.run(
        ["psql", "-X", "-w", "-d", database, "-tA", "-c", sql],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode:
        return None
    return result.stdout


def arch_is_jsonb(database):
    """La 16 stocke l'arch en varchar, la 17 et la 18 en jsonb."""
    sortie = run_psql(
        database,
        "SELECT data_type FROM information_schema.columns"
        " WHERE table_name='ir_ui_view' AND column_name='arch_db'",
    )
    return bool(sortie) and "jsonb" in sortie


# `arch_db` est un jsonb d'UNE ENTRÉE PAR LANGUE depuis la 17. N'en lire
# qu'une — et surtout n'en écrire qu'une — laisse la page cassée dans
# toutes les autres : mesuré sur /contact, réparé en en_US et toujours en
# 500 parce que le site rend en fr_CA.
def arch_expr(jsonb):
    return "arch_db" if jsonb else "json_build_object('', arch_db)"


def langs_of(arch):
    """{langue: texte}. La clé vide quand la version ne traduit pas l'arch."""
    if isinstance(arch, dict):
        return {k: v for k, v in arch.items() if isinstance(v, str)}
    return {"": arch} if isinstance(arch, str) else {}


def fetch(database, sql):
    """Rendre une liste de dictionnaires, ou None si la base se tait.

    Un seul aller-retour et du JSON plutôt qu'un découpage par lignes :
    un arch contient des sauts de ligne, et toute lecture ligne à ligne
    finirait par couper une vue en deux sans le dire.
    """
    sortie = run_psql(
        database, f"SELECT coalesce(json_agg(x), '[]') FROM ({sql}) x"
    )
    if sortie is None:
        return None
    try:
        return json.loads(sortie.strip() or "[]")
    except ValueError:
        return None


def cow_copies(database, jsonb):
    """Les copies faites par le site : website_id posé, aucun fichier.

    `arch_fs` vide est le discriminant : une copie qui garde un fichier
    est réécrite par la mise à jour du module, celle qui n'en a pas est
    du contenu d'utilisateur et ne l'est jamais.
    """
    return fetch(
        database,
        f"SELECT id, key, {arch_expr(jsonb)} AS arch FROM ir_ui_view"
        " WHERE website_id IS NOT NULL AND coalesce(arch_fs, '') = ''"
        " AND active",
    )


def children_of(database, jsonb, lst_id):
    """{parent: [enfants]} — les vues qui héritent d'une de ces copies."""
    if not lst_id:
        return {}
    ids = ",".join(str(i) for i in lst_id)
    lignes = fetch(
        database,
        f"SELECT id, key, inherit_id, {arch_expr(jsonb)} AS arch"
        f" FROM ir_ui_view WHERE inherit_id IN ({ids}) AND active",
    )
    dct = {}
    for ligne in lignes or []:
        dct.setdefault(ligne["inherit_id"], []).append(ligne)
    return dct


def module_twin(database, jsonb, cle):
    """L'arch de la vue MODULE de même clé, celle dont la copie est née."""
    lignes = fetch(
        database,
        f"SELECT {arch_expr(jsonb)} AS arch FROM ir_ui_view"
        f" WHERE key = '{cle}' AND website_id IS NULL"
        " AND coalesce(arch_fs, '') <> '' LIMIT 1",
    )
    return (lignes or [{}])[0].get("arch")


def known_keys(database):
    sortie = run_psql(
        database, "SELECT key FROM ir_ui_view WHERE key IS NOT NULL"
    )
    if sortie is None:
        return None
    return {ligne.strip() for ligne in sortie.splitlines() if ligne.strip()}


def parse(arch):
    """L'arbre, ou None si l'arch ne s'analyse pas."""
    from lxml import etree

    if not arch:
        return None
    try:
        return etree.fromstring(arch.encode("utf-8"))
    except Exception:
        return None


def anchors_wanted(arch_enfant):
    """Les expressions xpath qu'une vue héritière cherche dans son parent."""
    arbre = parse(arch_enfant)
    if arbre is None:
        return []
    return [
        noeud.get("expr") for noeud in arbre.iter("xpath") if noeud.get("expr")
    ]


def locates(arch, expr):
    """L'expression trouve-t-elle quelque chose dans cet arch ?

    Une expression illisible compte comme TROUVÉE : elle ne relève pas de
    cet outil, et la signaler comme un ancrage manquant enverrait
    réparer une vue qui n'a rien.
    """
    arbre = parse(arch)
    if arbre is None:
        return True
    try:
        return bool(arbre.xpath(expr))
    except Exception:
        return True


def dangling_calls(arch, connus):
    """Les `t-call` de cette arch vers un gabarit que la base n'a pas.

    Seuls les appels LITTÉRAUX : un `t-call` calculé se résout à
    l'exécution et l'on ne peut rien en dire ici.
    """
    arbre = parse(arch)
    if arbre is None:
        return []
    manquants = []
    for noeud in arbre.iter():
        nom = noeud.get("t-call")
        if not nom or "{" in nom or nom.startswith("#"):
            continue
        if nom not in connus and nom not in manquants:
            manquants.append(nom)
    return manquants


def signature(noeud):
    """De quoi reconnaître un élément d'un arch dans l'autre."""
    for attribut in ("t-call", "id", "t-name"):
        if noeud.get(attribut):
            return (noeud.tag, attribut, noeud.get(attribut))
    return (noeud.tag, None, None)


def find_by_signature(arbre, sig):
    tag, attribut, valeur = sig
    for noeud in arbre.iter(tag):
        if attribut is None:
            return noeud
        if noeud.get(attribut) == valeur:
            return noeud
    return None


def copie_de(noeud):
    from lxml import etree

    return etree.fromstring(etree.tostring(noeud))


def place_before(parent, ancre, accueil):
    """À quel rang poser l'ancrage dans `accueil`.

    On cherche le premier frère SUIVANT de l'ancrage que la copie possède
    aussi, et l'on se place juste devant. Sans aucun repère, en tête :
    un `t-set` en tête est toujours valide, jamais en retard.
    """
    suivants = list(parent)[list(parent).index(ancre) + 1 :]
    for frere in suivants:
        jumeau = find_by_signature(accueil, signature(frere))
        if jumeau is not None and jumeau.getparent() is accueil:
            return list(accueil).index(jumeau)
    return 0


def repair_anchor(arch_copie, arch_module, expr):
    """Remettre l'ancrage là où le module le place. None si impossible.

    On ne devine pas l'endroit : on lit dans le module quel élément
    CONTIENT l'ancrage, on retrouve le même dans la copie par sa
    signature, et l'on y insère en tête. Sans correspondance, on rend
    None — mieux vaut une réparation refusée qu'un bloc posé au hasard
    au milieu de la page de quelqu'un.
    """
    from lxml import etree

    module = parse(arch_module)
    copie = parse(arch_copie)
    if module is None or copie is None:
        return None
    try:
        cibles = module.xpath(expr)
    except Exception:
        return None
    if not cibles:
        return None
    ancre = cibles[0]
    parent = ancre.getparent()
    if parent is None:
        return None
    accueil = find_by_signature(copie, signature(parent))
    if accueil is None:
        return None
    # AVANT le même frère suivant, et non au même rang : la copie n'a
    # pas forcément les frères qui précèdent l'ancrage dans le module, et
    # « rang 1 » y désignerait alors une tout autre place. Ce qui doit
    # être respecté, c'est l'ORDRE — QWeb évalue dans l'ordre du
    # document, donc un `t-set` posé après le contenu qui s'en sert n'est
    # pas vu, et l'enfant qui s'insère « after » l'ancrage le suit.
    accueil.insert(place_before(parent, ancre, accueil), copie_de(ancre))
    return etree.tostring(copie, encoding="unicode")


def repair_call(arch_copie, nom):
    """Retirer l'appel au gabarit disparu. None si rien à retirer."""
    from lxml import etree

    copie = parse(arch_copie)
    if copie is None:
        return None
    retires = 0
    for noeud in list(copie.iter()):
        if noeud.get("t-call") != nom:
            continue
        parent = noeud.getparent()
        if parent is None:
            continue
        parent.remove(noeud)
        retires += 1
    if not retires:
        return None
    return etree.tostring(copie, encoding="unicode")


def any_lang(arch):
    """N'importe laquelle : les xpath d'une vue ne sont pas traduits."""
    langues = langs_of(arch)
    return langues.get("en_US") or (list(langues.values()) or [""])[0]


def audit(database):
    """Ce que chaque copie a de cassé. None si la base ne répond pas."""
    jsonb = arch_is_jsonb(database)
    copies = cow_copies(database, jsonb)
    connus = known_keys(database)
    if copies is None or connus is None:
        return None
    enfants = children_of(database, jsonb, [c["id"] for c in copies])
    rapport = []
    for copie in copies:
        manque = []
        pendants = []
        for langue, texte in sorted(langs_of(copie["arch"]).items()):
            for enfant in enfants.get(copie["id"], []):
                # L'enfant a lui aussi ses langues ; une seule suffit à
                # connaître ses xpath, ils ne sont pas traduits.
                for expr in anchors_wanted(any_lang(enfant["arch"])):
                    if not locates(texte, expr):
                        manque.append(
                            {
                                "enfant": enfant["id"],
                                "expr": expr,
                                "langue": langue,
                            }
                        )
            for nom in dangling_calls(texte, connus):
                if nom not in pendants:
                    pendants.append(nom)
        if manque or pendants:
            rapport.append(
                {
                    "id": copie["id"],
                    "key": copie["key"],
                    "anchors": manque,
                    "calls": pendants,
                }
            )
    return {"database": database, "jsonb": jsonb, "views": rapport}


def write_arch_sql(vue_id, langues, jsonb):
    """La mise à jour, TOUTES les langues d'un coup.

    Réécrire une seule entrée du jsonb laisse la page cassée dans les
    autres : mesuré sur /contact, réparé en en_US et toujours en 500
    parce que le site rend en fr_CA.

    Dollar-quoting, parce qu'un arch porte une apostrophe à presque
    chaque attribut. Le marqueur est assez long pour qu'aucun gabarit ne
    le contienne par accident.
    """
    if not jsonb:
        texte = langues.get("") or next(iter(langues.values()), "")
        return (
            f"UPDATE ir_ui_view SET arch_db = $elcow${texte}$elcow$"
            f" WHERE id = {vue_id};"
        )
    paires = ", ".join(
        f"$elcow${langue}$elcow$, $elcow${texte}$elcow$"
        for langue, texte in sorted(langues.items())
    )
    return (
        f"UPDATE ir_ui_view SET arch_db = jsonb_build_object({paires})"
        f" WHERE id = {vue_id};"
    )


def plan(database, rapport):
    """[(id, clé, geste, quoi, sql)] — ce que `--apply` ferait, rien de plus.

    Les réparations s'enchaînent sur le MÊME texte, langue par langue, et
    une seule écriture les porte toutes : deux UPDATE sur la même vue et
    le second effacerait le premier.
    """
    jsonb = rapport["jsonb"]
    gestes = []
    for vue in rapport["views"]:
        ligne = cow_copies_one(database, jsonb, vue["id"])
        if not ligne:
            continue
        langues = langs_of(ligne["arch"])
        module = module_twin(database, jsonb, vue["key"])
        arch_module = any_lang(module) if module else None
        touche = False
        for langue in sorted(langues):
            texte = langues[langue]
            for manque in vue["anchors"]:
                if locates(texte, manque["expr"]):
                    continue
                neuf_texte = (
                    repair_anchor(texte, arch_module, manque["expr"])
                    if arch_module
                    else None
                )
                if neuf_texte is None:
                    gestes.append(
                        (
                            vue["id"],
                            vue["key"],
                            "anchor-impossible",
                            f"{manque['expr']} [{langue or '—'}]",
                            None,
                        )
                    )
                    continue
                texte = neuf_texte
                touche = True
                gestes.append(
                    (
                        vue["id"],
                        vue["key"],
                        "anchor",
                        f"{manque['expr']} [{langue or '—'}]",
                        None,
                    )
                )
            for nom in vue["calls"]:
                neuf_texte = repair_call(texte, nom)
                if neuf_texte is None:
                    continue
                texte = neuf_texte
                touche = True
                gestes.append(
                    (
                        vue["id"],
                        vue["key"],
                        "t-call",
                        f"{nom} [{langue or '—'}]",
                        None,
                    )
                )
            langues[langue] = texte
        if touche:
            gestes.append(
                (
                    vue["id"],
                    vue["key"],
                    "write",
                    f"{len(langues)} langue(s)",
                    write_arch_sql(vue["id"], langues, jsonb),
                )
            )
    return gestes


def cow_copies_one(database, jsonb, vue_id):
    lignes = fetch(
        database,
        f"SELECT id, key, {arch_expr(jsonb)} AS arch FROM ir_ui_view"
        f" WHERE id = {vue_id}",
    )
    return (lignes or [None])[0]


def render(rapport, gestes):
    if not rapport["views"]:
        return [f"✅ {t('Every website copy still renders.')}"]
    lignes = [
        f"🖼  {t('Website copies that can no longer render')}"
        f" — {rapport['database']}",
        "",
    ]
    for vue in rapport["views"]:
        lignes.append(f"   [{vue['id']}] {vue['key']}")
        for manque in vue["anchors"]:
            lignes.append(
                f"      ⚓ {t('anchor missing for view')} {manque['enfant']} :"
                f" {manque['expr']}"
            )
        for nom in vue["calls"]:
            lignes.append(
                f"      ☎ {t('calls a template that is gone:')} {nom}"
            )
    impossibles = [g for g in gestes if g[2] == "anchor-impossible"]
    faisables = [g for g in gestes if g[2] in ("anchor", "t-call")]
    lignes.append("")
    lignes.append(
        f"   {len(faisables)} {t('repair(s) available with --apply')}"
    )
    if impossibles:
        lignes.append(
            f"   ⚠ {len(impossibles)} {t('cannot be repaired automatically')}"
        )
    if any(g[2] == "t-call" for g in faisables):
        lignes.append(
            f"   {t('Removing a call removes its block from the page.')}"
        )
    return lignes


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Report website COW copies that can no longer render after a"
            " version bump, and optionally repair them."
        )
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually repair (default: report only)",
    )
    parser.add_argument("--json", action="store_true", help="machine output")
    config = parser.parse_args(argv)

    rapport = audit(config.database)
    if rapport is None:
        print(f"❌ {t('Cannot read the database: ')}{config.database}")
        return 2
    gestes = plan(config.database, rapport)
    if config.json:
        print(
            json.dumps(rapport, indent=2, sort_keys=True, ensure_ascii=False)
        )
        return 1 if rapport["views"] else 0
    if not rapport["views"]:
        print("\n".join(render(rapport, gestes)))
        return 0
    if not config.apply:
        print("\n".join(render(rapport, gestes)))
        return 1

    for _id, _cle, genre, _quoi, sql in gestes:
        if sql and run_psql(config.database, sql, read_only=False) is None:
            print(f"❌ {t('The correction failed.')}")
            return 2
    # RELIRE : annoncer « corrigé » sans regarder ferait rouvrir la même
    # page cassée en croyant le problème derrière soi.
    apres = audit(config.database)
    if apres is None:
        print(f"❌ {t('Cannot read the database: ')}{config.database}")
        return 2
    if apres["views"]:
        print("\n".join(render(apres, plan(config.database, apres))))
        print(f"⚠️  {t('Some copies still cannot render.')}")
        return 1
    print(f"✅ {t('Every website copy renders again.')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
