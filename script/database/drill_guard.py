#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Cette base est-elle un EXERCICE ? La seule fonction qui puisse le dire.

Un chemin qui détruit doit demander ici, et nulle part ailleurs. Le prédicat
arrive donc AVANT l'exercice de restauration qui s'en servira : une garde
écrite après le geste qu'elle garde n'a jamais gardé ce geste.

LE NOM NE PROUVE RIEN. Le dépôt en porte le relevé : sept bases dont le
nom portait la marque de neutralisation, le drapeau absent des sept, des
dizaines de tâches planifiées encore actives. Le nom ne sert donc que de
POIGNÉE de connexion — c'est la seule chose qu'on n'interroge pas. Un
prédicat nominal manipulerait d'ailleurs mécaniquement des noms de clients,
qui n'ont pas le droit de vivre hors de la configuration privée.

CE QU'IL LIT, ET POURQUOI CHACUN. Deux témoins POSITIFS, disjoints parce que
les deux façons de fabriquer une copie laissent des traces différentes : la
route récente pose un drapeau et ne crée pas de compte d'essai, l'ancienne
crée le compte et ne pose pas le drapeau. Exiger les deux déclarerait
« réelle » la moitié des copies que l'outillage fabrique lui-même — d'où
l'un OU l'autre. Puis deux VETOS : un fournisseur de paiement vivant ou une
tâche planifiée active disqualifient, quel que soit le drapeau. Une copie
qui envoie des courriels ou encaisse n'est pas un exercice, même si on l'a
marquée comme tel.

TOUT EN COUNT, ET JAMAIS EN LIGNES. Une requête refusée et zéro ligne
rendent la même liste vide : le dépôt l'a déjà payé, un identifiant ambigu
passait pour « pas de compte d'essai » et l'outil annonçait tranquillement
qu'une base n'était pas neutralisée. Un COUNT rend toujours une ligne quand
la requête aboutit, donc l'absence se distingue du silence.

CE QU'IL NE SAIT PAS, IL LE REFUSE. Illisible ne veut pas dire exercice ; le
doute penche du côté qui ne promet rien. Et il ne DÉTRUIT rien, ne propose
rien, n'affiche rien : il rend un jeton, l'écran l'écrit.
"""

from __future__ import annotations

from typing import NamedTuple

# Le vocabulaire des verdicts, clos. Un cinquième cas se déclare ici, où les
# appelants le verront, plutôt que de se glisser dans une chaîne libre.
DRILL = "drill"
REAL = "real"
UNREADABLE = "unreadable"
NOT_ODOO = "not-odoo"
VERDICTS = (DRILL, REAL, UNREADABLE, NOT_ODOO)

# Le compte d'essai que l'ancienne route de copie laisse derrière elle. Son
# module est désinstallé, l'utilisateur survit : c'est justement ce qui en
# fait une trace.
DRILL_LOGIN = "test"

# Le compte actif portant ce login. Écrit ici et non emprunté : le module
# qui porte la même question s'importe par un chemin dépendant du répertoire
# courant, et une garde ne se met pas à la merci d'un « sys.path ».
TEST_USER_SQL = "SELECT count(*) FROM res_users WHERE login = '%s' AND active"

# La base est-elle seulement une base Odoo ? En COUNT comme les autres, et
# par le MÊME lecteur : le contrôle du dépôt qui pose cette question ouvre
# sa propre connexion, si bien qu'un lecteur injecté ne le traverse pas — et
# une garde qu'on ne peut pas éprouver sans serveur ne s'éprouve pas.
ODOO_SQL = (
    "SELECT count(*) FROM information_schema.tables"
    " WHERE table_schema = 'public' AND table_name = 'ir_module_module'"
)


class Inspection(NamedTuple):
    """Ce que la base a répondu, et ce qu'on en conclut.

    Les COMPTES voyagent avec le verdict : un rapport qui dit « réelle »
    sans dire ce qui l'a disqualifiée envoie chercher au hasard. Ce sont
    des comptes et jamais des valeurs — un rapport finit dans un billet.

    `None` veut dire « pas lu », et se distingue de zéro.
    """

    verdict: str
    flag: int | None = None
    test_user: int | None = None
    payment_live: int | None = None
    cron_active: int | None = None
    detail: str = ""


def _run_psql_par_defaut():
    """Le lecteur du dépôt, importé À L'APPEL et non au chargement.

    Importé en tête, il rendrait ce module inutilisable là où sa dépendance
    manque — or une garde doit pouvoir être lue, éprouvée et importée
    partout, y compris là où rien n'est installé.
    """
    from script.analyse.lib_analyse import run_psql

    return run_psql


def _premier_champ(sortie):
    """Le premier champ de la première ligne, quelle que soit la forme.

    DEUX FORMES DE SORTIE COEXISTENT, et les confondre coûte les comptes.
    Le lecteur du dépôt lance psql en « -tAc » et rend sa sortie BRUTE :
    une CHAÎNE. Un lecteur injecté rend une liste de lignes. Un
    `sortie[0][0]` qui convient à la seconde lit, sur la première, le
    premier CARACTÈRE — « 250 » devient « 2 ».

    Le verdict y survivait par accident : le premier chiffre d'un entier
    positif n'est jamais zéro, donc la véracité booléenne se conservait.
    Les comptes, eux, sont faux dès qu'ils dépassent neuf — et l'inspection
    promet de les faire voyager pour qu'un rapport n'envoie pas chercher au
    hasard.

    None veut dire « rien à lire », jamais zéro.
    """
    if sortie is None:
        return None
    if isinstance(sortie, str):
        lignes = sortie.strip().splitlines()
        return lignes[0].strip() if lignes else None
    if not sortie:
        return None
    ligne = sortie[0]
    if isinstance(ligne, str):
        return ligne.strip()
    return ligne[0] if ligne else None


def _compte(run_psql, database, sql):
    """Le nombre que rend un COUNT, ou None si la requête n'a pas abouti.

    None et zéro ne sont PAS la même chose : l'un dit qu'on n'a pas pu
    regarder, l'autre qu'on a regardé et qu'il n'y a rien. Les confondre
    fait passer une base illisible pour une base propre.
    """
    try:
        sortie = run_psql(database, sql)
    except Exception:
        return None
    champ = _premier_champ(sortie)
    if champ is None:
        return None
    try:
        return int(champ)
    except (TypeError, ValueError):
        return None


def inspect(database, run_psql=None) -> Inspection:
    """Interroge la base et NOMME ce qu'elle est. Ne lève pas.

    `run_psql` est injectable : c'est ce qui rend la décision vérifiable
    sans serveur, et c'est le seul geste de ce module qui parlerait à
    quelque chose.

    NE PAS LEVER SE TIENT ICI, et non chez l'appelant. Les deux imports
    tardifs s'exécutent à chaque appel : hors de tout garde-fou, ils
    rendaient une trace d'exception là où la docstring promet un verdict,
    dès que le module est chargé autrement que par le paquet `script`. Un
    appelant qui croit la promesse ouvrait alors la porte que la garde
    existe pour tenir — un import manquant n'est pas un feu vert, c'est
    une lecture qui n'a pas eu lieu.
    """
    try:
        from script.analyse.monitoring import NEUTRALIZE_SQL
    except Exception as souci:
        return Inspection(UNREADABLE, detail=f"monitoring ({souci})")

    if run_psql is None:
        try:
            run_psql = _run_psql_par_defaut()
        except Exception as souci:
            return Inspection(UNREADABLE, detail=f"psql ({souci})")

    # Sans cette question, une base vide rend « relation inexistante » sur
    # chaque contrôle, et quatre illisibles se lisent comme une base qu'on
    # n'a pas su lire — alors que ce n'était pas une base Odoo.
    odoo = _compte(run_psql, database, ODOO_SQL)
    if odoo is None:
        return Inspection(UNREADABLE, detail="odoo")
    if not odoo:
        return Inspection(NOT_ODOO)

    flag = _compte(run_psql, database, NEUTRALIZE_SQL["flag"])
    utilisateur = _compte(run_psql, database, TEST_USER_SQL % DRILL_LOGIN)
    paiement = _compte(run_psql, database, NEUTRALIZE_SQL["payment_live"])
    taches = _compte(run_psql, database, NEUTRALIZE_SQL["cron_active"])

    comptes = dict(
        flag=flag,
        test_user=utilisateur,
        payment_live=paiement,
        cron_active=taches,
    )
    # UN SEUL CONTRÔLE ILLISIBLE SUFFIT À REFUSER. Se prononcer sur trois
    # réponses quand la quatrième manque, c'est parier que la manquante
    # allait dans le même sens.
    if any(valeur is None for valeur in comptes.values()):
        manquants = sorted(
            nom for nom, valeur in comptes.items() if valeur is None
        )
        return Inspection(UNREADABLE, detail=", ".join(manquants), **comptes)
    if paiement or taches:
        return Inspection(REAL, **comptes)
    if flag or utilisateur:
        return Inspection(DRILL, **comptes)
    return Inspection(REAL, **comptes)


def is_drill_database(database, run_psql=None) -> bool:
    """Le feu vert, et rien d'autre. Vrai sur le SEUL verdict d'exercice.

    Un booléen là où l'inspection rend un jeton : un appelant qui détruit
    n'a pas à connaître le vocabulaire, il a besoin d'une porte. Celui qui
    veut DIRE pourquoi appelle `inspect`.
    """
    return inspect(database, run_psql=run_psql).verdict == DRILL
