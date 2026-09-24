#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le contexte déclaré d'un gpt : ce qu'il a le droit de lire, et de dire.

Un gpt déclare des fichiers et des commandes ; ce module les lit, les borne,
les balaie, et rend le texte assemblé avec ce qu'il y a trouvé. Il ne décide
jamais d'envoyer : c'est le menu qui pose la porte à l'utilisateur, et
`gate` lui donne le verdict à afficher.

**La liste de refus passe avant tout, et se résout sur le chemin RÉEL.** Ni
« suivi par git » ni « ignoré par git » ne sont des portes utilisables :
`private/` est partiellement suivi, et `tasks/` n'est pas dans `.gitignore`.
Un lien symbolique est donc résolu avant d'être comparé, sinon un lien vers
`private/` traverserait la liste en la contournant par le nom.

**Une commande est un `argv`, jamais une chaîne d'interpréteur**, et elle est
confrontée à une liste d'autorisation qui vit dans le dépôt — un gpt venu
d'ailleurs ne peut donc pas l'étendre. Le refus d'un métacaractère dans un
argument n'est PAS une protection contre l'injection : sans interpréteur, il
n'y a rien à injecter. C'est un signal que l'auteur croyait écrire une ligne
de shell, donc que son gpt ne fera pas ce qu'il voulait — le lui dire au
chargement vaut mieux qu'un résultat surprenant.

**Les plafonds servent la lisibilité autant que le coût.** Un contexte qu'on
ne peut plus relire avant de l'envoyer n'est plus un contexte déclaré, c'est
un versement. La coupe se fait sur une frontière de ligne et porte une marque,
pour qu'une source tronquée se voie.

**Ce que le balayage voit, et ce qu'il ne voit pas.** `identifiants()`
reconnaît les adresses, les courriels et les chemins de compte. Il ne
reconnaît PAS les noms — d'hôte, de client, de base de données — sauf si
`private/noms_interdits.txt` les énumère, et ce fichier n'existe pas
d'ordinaire. La moitié « noms » du filtre est donc inerte par défaut, et
`gate` le dit au lieu de laisser croire à un contrôle complet : une
destination tierce est REFUSÉE tant que cette liste est vide.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from script import lib_identifiant

# Ce qu'aucun contexte ne lit, jamais, quel que soit le gpt qui le demande.
# `private/` est le seul endroit autorisé à porter une donnée de client ;
# `tasks/` porte l'enquête, que la convention y envoie pour qu'elle ne suive
# pas le dépôt ; le reste est un coffre, une clé, un cache ou un historique.
REFUS = (
    "private",
    "tasks",
    ".git",
    ".ssh",
    ".erplibre",
    ".venv",
    "node_modules",
)

# Les suffixes refusés où qu'ils soient : un coffre reste un coffre.
SUFFIXES_REFUSES = (".kdbx", ".key", ".pem")

# Les commandes qu'un gpt peut déclarer, par PRÉFIXE d'argv. La liste vit
# dans le dépôt et n'est pas extensible depuis un gpt : c'est ce qui rend
# inoffensif un fichier que personne n'a relu.
AUTORISEES = (
    ("python3", "script/analyse/check_comment_hygiene.py"),
    ("python3", "script/analyse/check_manifest_gaps.py"),
    ("git", "diff"),
    ("git", "log"),
    ("git", "status"),
    ("./script/test/run_unit_test.sh",),
)

# Les caractères qui trahissent un auteur qui croyait écrire du shell.
METACARACTERES = ";|&><`$\n"

# Ce qu'une source peut peser, et ce que tout le contexte peut peser. Un
# contexte qu'on ne peut plus relire avant l'envoi n'est plus déclaré.
MAX_PAR_SOURCE = 8_000
MAX_TOTAL = 24_000

# Ce qu'une commande a le droit de durer, et ce que toutes ont ensemble. Une
# commande qui dépasse laisse le menu rendre la main plutôt que d'attendre.
DELAI_PAR_COMMANDE = 30
DELAI_TOTAL = 60

# La marque d'une source coupée. Elle est visible dans l'aperçu, donc la
# troncature ne se découvre pas dans la réponse du modèle.
MARQUE_COUPE = "… [cut]"

# Les verdicts de la porte.
OK = "ok"
AVERTIR = "warn"
BLOQUER = "block"

# Les clés de la porte, nommées une fois. Voir la raison dans `gpt.py`.
NOMS_INVERIFIABLES = (
    "private/noms_interdits.txt is absent: no client, database, VM or host"
    " name can be recognized."
)
TROUVAILLE_BLOQUE_UN_TIERS = (
    "A finding blocks a send to a third party. No override."
)
TROUVAILLE_A_RELIRE = "finding to re-read before sending"


class ContextRefused(Exception):
    """Une source qu'aucun gpt n'a le droit de lire, ou un argv refusé.

    Le message porte la raison en clair : il s'affiche tel quel dans les
    problèmes du catalogue, à côté de la source refusée.
    """


def repo_root() -> Path:
    """La racine du dépôt, dérivée de l'emplacement de ce module."""
    return Path(__file__).resolve().parents[3]


def resolve_file(path, *, root=None) -> Path:
    """Le chemin réel d'une source déclarée. Lève `ContextRefused`.

    Deux refus, dans cet ordre. Le chemin est d'abord RÉSOLU — liens
    symboliques compris — puis comparé : un lien vers `private/` ne doit pas
    passer parce que son nom, lui, est anodin. Ensuite il doit rester SOUS la
    racine du dépôt : un contexte n'a rien à lire ailleurs, et « ../ » est le
    chemin le plus court vers le répertoire personnel.
    """
    base = Path(root).resolve() if root else repo_root()
    reel = (base / Path(path)).resolve()
    try:
        relatif = reel.relative_to(base)
    except ValueError:
        raise ContextRefused(f"hors du dépôt : {path}") from None
    if reel.suffix in SUFFIXES_REFUSES:
        raise ContextRefused(f"suffixe refusé : {reel.suffix}")
    for partie in relatif.parts:
        if partie in REFUS or partie.startswith(".venv"):
            raise ContextRefused(f"chemin refusé : {partie}")
    return reel


def check_argv(argv) -> tuple:
    """L'argv d'une commande déclarée. Lève `ContextRefused`. Fonction PURE.

    Une chaîne est refusée d'emblée : elle voudrait dire qu'un interpréteur
    la relira, et c'est justement ce qu'aucun contexte ne fait.
    """
    if isinstance(argv, str):
        raise ContextRefused("une commande est une liste, pas une chaîne")
    if not isinstance(argv, (list, tuple)) or not argv:
        raise ContextRefused("commande vide")
    morceaux = []
    for morceau in argv:
        if not isinstance(morceau, str):
            raise ContextRefused(f"argument non textuel : {morceau!r}")
        if any(caractere in morceau for caractere in METACARACTERES):
            # Sans interpréteur il n'y a rien à injecter : ce refus dit que
            # l'auteur croyait écrire du shell, donc que son gpt ne fera pas
            # ce qu'il voulait.
            raise ContextRefused(f"métacaractère d'interpréteur : {morceau}")
        morceaux.append(morceau)
    for prefixe in AUTORISEES:
        if tuple(morceaux[: len(prefixe)]) == prefixe:
            return tuple(morceaux)
    raise ContextRefused(f"hors liste d'autorisation : {morceaux[0]}")


def substituer(argv, inputs=None) -> list:
    """`argv` avec ses `{nom}` remplacés. Lève `ContextRefused`.

    L'ORDRE compte, et c'est tout l'enjeu : la substitution a lieu AVANT
    `check_argv`, jamais après. Une valeur saisie par l'utilisateur passe donc
    par le contrôle des métacaractères et de la liste d'autorisation comme le
    reste de la ligne — vérifier le gabarit puis y injecter une valeur
    reviendrait à vérifier ce qu'on n'exécute pas.

    Un `{nom}` sans valeur est refusé plutôt que laissé tel quel : une
    commande qui recevrait « {test_file} » comme chemin échouerait plus loin,
    avec une erreur qui ne dirait pas d'où elle vient.
    """
    valeurs = dict(inputs or {})
    remplis = []
    for morceau in argv or ():
        if not isinstance(morceau, str):
            remplis.append(morceau)
            continue
        for nom, valeur in valeurs.items():
            morceau = morceau.replace("{" + nom + "}", str(valeur))
        manquant = re.search(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", morceau)
        if manquant:
            raise ContextRefused(f"entrée sans valeur : {manquant.group(1)}")
        remplis.append(morceau)
    return remplis


def borner(texte, maximum=MAX_PAR_SOURCE) -> str:
    """`texte` ramené sous `maximum`, coupé sur une frontière de ligne.

    La coupe se voit : sans marque, une source tronquée se lit comme une
    source complète, et le modèle répond sur ce qu'il n'a pas reçu.
    """
    if len(texte) <= maximum:
        return texte
    coupe = texte[:maximum]
    frontiere = coupe.rfind("\n")
    if frontiere > 0:
        coupe = coupe[:frontiere]
    return coupe + "\n" + MARQUE_COUPE


def assemble(
    files=(),
    commands=(),
    *,
    inputs=None,
    read=None,
    run=None,
    termes=None,
    root=None,
):
    """Le contexte assemblé, et ce que le balayage y a trouvé.

    Rend `(texte, trouvailles)`. Chaque trouvaille est un dictionnaire
    `{source, motif, extrait, position}` : le menu les surligne dans
    l'aperçu, et `gate` décide de ce qu'elles autorisent.

    Les sources sont lues dans l'ordre déclaré, chacune bornée, et
    l'assemblage s'arrête net au plafond total : une source qui n'entre pas
    est ANNONCÉE plutôt que silencieusement absente.

    `read`, `run` et `termes` sont injectés — un test décide alors ce que la
    machine contient, ce que les commandes rendent, et quels noms le filtre
    connaît, sans dépendre du poste qui le lance.
    """
    lecteur = read or _lire
    lanceur = run or _lancer
    liste = lib_identifiant.termes_interdits() if termes is None else termes

    morceaux: list[str] = []
    trouvailles: list[dict] = []
    total = 0
    reste_delai = DELAI_TOTAL

    for chemin in files or ():
        libelle = str(chemin)
        try:
            chemin = substituer([str(chemin)], inputs)[0]
            reel = resolve_file(chemin, root=root)
            contenu = lecteur(reel)
        except (ContextRefused, OSError) as refus:
            morceaux.append(f"# {libelle} — {refus}")
            continue
        contenu, total, plein = _ajouter(contenu, total)
        morceaux.append(f"# {libelle}\n{contenu}")
        trouvailles.extend(_balayer(contenu, libelle, liste))
        if plein:
            morceaux.append(f"# {MARQUE_COUPE}")
            return "\n\n".join(morceaux), trouvailles

    for commande in commands or ():
        libelle = _libelle(commande)
        try:
            argv = check_argv(substituer(_argv(commande), inputs))
        except ContextRefused as refus:
            morceaux.append(f"# {libelle} — {refus}")
            continue
        delai = min(DELAI_PAR_COMMANDE, reste_delai)
        if delai <= 0:
            morceaux.append(f"# {libelle} — délai total épuisé")
            continue
        try:
            sortie = lanceur(argv, delai)
        except Exception as panne:
            morceaux.append(f"# {libelle} — {panne}")
            continue
        reste_delai -= delai
        sortie, total, plein = _ajouter(sortie or "", total)
        morceaux.append(f"# {libelle}\n{sortie}")
        trouvailles.extend(_balayer(sortie, libelle, liste))
        if plein:
            morceaux.append(f"# {MARQUE_COUPE}")
            break

    return "\n\n".join(morceaux), trouvailles


def gate(trouvailles, hosting, *, names_checkable=True) -> tuple:
    """Ce que la porte autorise. Rend `(verdict, clé)`. Fonction PURE.

    Trois verdicts. `ok` laisse passer. `warn` demande une confirmation que
    l'utilisateur peut donner. `block` REFUSE sans passe-droit.

    La règle tient à qui reçoit. Sur la boucle locale, une trouvaille est un
    avertissement : rien ne quitte la machine, et l'opérateur décide chez lui.
    Vers un TIERS, elle bloque — une adresse ou un chemin de compte envoyé à
    quelqu'un d'autre ne se rattrape pas.

    `names_checkable` dit si la liste des noms interdits est renseignée.
    Vide, la moitié « noms » du filtre est inerte : le balayage ne verrait ni
    nom d'hôte, ni nom de client, ni nom de base. Un envoi vers un tiers est
    alors refusé même SANS trouvaille, parce que l'absence de trouvaille ne
    prouve plus rien.
    """
    tiers = hosting not in ("loopback", "lan")
    if tiers and not names_checkable:
        return (
            BLOQUER,
            NOMS_INVERIFIABLES,
        )
    if not trouvailles:
        return OK, ""
    if tiers:
        return (
            BLOQUER,
            TROUVAILLE_BLOQUE_UN_TIERS,
        )
    return AVERTIR, TROUVAILLE_A_RELIRE


def _ajouter(contenu, total):
    """(contenu borné, nouveau total, plafond atteint)."""
    contenu = borner(contenu, MAX_PAR_SOURCE)
    place = MAX_TOTAL - total
    if len(contenu) >= place:
        return borner(contenu, max(place, 0)), MAX_TOTAL, True
    return contenu, total + len(contenu), False


def _balayer(texte, source, termes):
    """Les données identifiantes d'une source, nommées par leur source.

    Le filtre reconnaît les adresses, les courriels et les chemins de compte.
    Les NOMS ne lui sont connus que par `termes`, d'où l'injection : une
    liste vide rend un balayage muet sur toute une classe de données.
    """
    return [
        {
            "source": source,
            "motif": motif,
            "extrait": extrait,
            "position": position,
        }
        for motif, extrait, position in lib_identifiant.identifiants(
            texte, termes=tuple(termes or ())
        )
    ]


def _argv(commande):
    """L'argv d'une commande déclarée, quelle que soit sa forme."""
    if isinstance(commande, dict):
        return commande.get("argv")
    return commande


def _libelle(commande):
    """Ce qui nomme une commande dans l'aperçu.

    Le libellé de l'auteur s'il en donne un : « Trouvailles » se lit mieux
    qu'une ligne d'argv, et c'est cet aperçu que l'utilisateur relit.
    """
    if isinstance(commande, dict):
        etiquette = commande.get("label")
        if isinstance(etiquette, str) and etiquette.strip():
            return etiquette.strip()
        argv = commande.get("argv") or ()
    else:
        argv = commande or ()
    return " ".join(str(morceau) for morceau in argv)[:80]


def _lire(chemin):
    """Le texte d'une source de contexte."""
    return Path(chemin).read_text(encoding="utf-8", errors="replace")


def _lancer(argv, delai):
    """La sortie standard d'une commande déclarée, sans interpréteur.

    `cwd` est la racine du dépôt : un gpt déclare des chemins relatifs à
    elle, et non au répertoire d'où le menu a été lancé. La sortie d'erreur
    est jointe — une commande qui explique pourquoi elle n'a rien produit est
    plus utile qu'un vide.
    """
    answer = subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        timeout=delai,
        cwd=str(repo_root()),
        env={**os.environ, "LC_ALL": "C", "LANG": "C"},
    )
    return answer.stdout + (answer.stderr if answer.returncode else "")
