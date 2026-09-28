#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'environnement d'une session, lu sans le recopier en clair.

Le noyau tient déjà la frontière : `/proc/<pid>/environ` est en mode 400,
réservé au propriétaire du processus, là où `cmdline` est public. Un écran qui
recopie une valeur en clair la rend copiable, capturable, collable dans un
rapport ou un commit — il casse une protection que personne n'a eu à écrire.
L'asymétrie décide de tout ce module : une valeur masquée à tort coûte une
commande que l'utilisateur a le droit de lancer sur son propre processus ; une
valeur affichée à tort ne se retire plus.

**Le découpage d'abord, parce que c'est lui qui fuit.** Une valeur peut porter
des sauts de ligne — une invite de shell en porte — donc `tr '\\0' '\\n'` puis
`cut -d= -f1` rend des fragments de VALEUR au milieu d'une liste de NOMS : sur
un processus mesuré, vingt-neuf « noms » pour vingt-sept variables, dont un de
deux cent cinquante-neuf caractères. La lecture se fait donc en binaire, la
séparation sur l'octet nul, la coupure sur le PREMIER `=`, et tout nom qui
n'est pas un identifiant est rejeté.

**Une liste blanche, et non un filtre de motifs.** Le masquage par motif du
dépôt — `redact_secrets` — ne reconnaît que la forme `NOM=valeur` collée ; en
deux colonnes alignées il laisse passer la quasi-totalité des noms, `API_KEY`
compris. Un filtre bâti sur la forme du texte est inadapté à un tableau : la
valeur ne s'affiche donc que si son nom est déclaré ici ET que sa valeur a la
forme attendue de ce nom.

**Ce que la liste blanche rate, dans les deux sens.** Elle ne protège pas d'une
valeur détournée dans un nom autorisé — une liste d'URL peut porter un
`compte:jeton@`, d'où le contrôle de forme. Et elle masque toute variable neuve
et utile jusqu'à inscription. C'est pourquoi une seule variable se démasque à
la demande, jamais le bloc.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Un nom de variable d'environnement. Tout ce qui n'y répond pas est un
# fragment de valeur, et n'a rien à faire dans une liste de noms.
NOM = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Les noms dont la valeur s'affiche, et la forme que cette valeur doit avoir.
# La forme est ce qui rattrape une valeur détournée dans un nom autorisé.
PERMIS = {
    "LANG": re.compile(r"^[A-Za-z0-9_.\-@]{2,32}$"),
    "TERM": re.compile(r"^[A-Za-z0-9_.\-]{1,32}$"),
    "SHELL": re.compile(r"^/[A-Za-z0-9_/\-.]{1,40}$"),
    "SHLVL": re.compile(r"^\d{1,3}$"),
    "MOTD_SHOWN": re.compile(r"^[A-Za-z0-9_\-]{1,16}$"),
    "STARSHIP_SHELL": re.compile(r"^[A-Za-z0-9_\-]{1,16}$"),
    "XDG_SESSION_TYPE": re.compile(r"^[A-Za-z0-9_\-]{1,16}$"),
    "XDG_SESSION_CLASS": re.compile(r"^[A-Za-z0-9_\-]{1,16}$"),
    "XDG_SESSION_ID": re.compile(r"^\d{1,8}$"),
    "VIRTUAL_ENV_PROMPT": re.compile(r"^[A-Za-z0-9_.\-()]{1,40}$"),
    "COLORTERM": re.compile(r"^[A-Za-z0-9_\-]{1,24}$"),
}

# Ce qui ne montre même pas sa longueur. Un nom qui porte l'un de ces mots
# désigne un secret, et la longueur d'un secret est déjà un renseignement.
SECRET = re.compile(
    r"AUTH|TOKEN|SECRET|KEY|PASSWORD|PASSWD|CRED|COOKIE|BRIDGE|SESSION_KEY",
    re.IGNORECASE,
)

# Les familles dont l'absence mérite d'être dite. Un utilisateur qui a activé
# la télémétrie et ne la voit pas ici chercherait pourquoi : la réponse est
# que le processus porte l'environnement du shell de connexion, figé à l'exec,
# et que les variables de Claude Code vivent dans ses processus-ENFANTS.
FAMILLES = ("CLAUDE_", "ANTHROPIC_", "OTEL_")

# La forme rendue à la place d'une valeur masquée, selon ce qu'elle est.
MASQUE = "<masqué>"


@dataclass(frozen=True)
class Variable:
    """Un nom, et ce qu'on a le droit d'en montrer.

    `valeur` est la valeur réelle quand elle est affichable, sinon la chaîne
    vide. `forme` est ce que l'écran montre à sa place — « <chemin> »,
    « <33 car.> », « <masqué> ». `secret` dit que même la longueur se tait.
    """

    nom: str
    valeur: str = ""
    forme: str = ""
    secret: bool = False

    @property
    def visible(self) -> bool:
        return bool(self.valeur)


def _forme(valeur: str) -> str:
    """Ce qu'on montre d'une valeur qu'on ne montre pas.

    La forme dit assez pour diagnostiquer — « c'est un chemin », « c'est vide »
    — sans rien recopier. La longueur est donnée parce qu'elle distingue une
    variable vide d'une variable pleine, ce qui est souvent toute la question.
    """
    if not valeur:
        return "<vide>"
    if valeur.startswith("/") and "\n" not in valeur:
        return "<chemin>"
    return f"<{len(valeur)} car.>"


def lire_environ(pid, *, ouvrir=None) -> bytes | None:
    """Les octets bruts de l'environnement, ou None s'il n'est pas lisible.

    None et b"" ne disent pas la même chose : le premier est « le processus a
    disparu, ou appartient à un autre compte », le second « le processus n'a
    aucune variable ». Un écran qui les confond annonce zéro variable là où il
    n'a rien pu lire.
    """
    if ouvrir is None:

        def ouvrir(chemin):
            return open(chemin, "rb")

    try:
        with ouvrir(f"/proc/{int(pid)}/environ") as fh:
            return fh.read()
    except (OSError, ValueError, TypeError):
        return None


def decouper(brut) -> list[tuple[str, str]]:
    """(nom, valeur) de chaque entrée bien formée. Fonction PURE.

    Séparation sur l'octet nul, coupure sur le PREMIER `=`, et rejet de tout
    nom qui n'est pas un identifiant. Ce dernier filtre est ce qui empêche un
    fragment de valeur multiligne de s'afficher comme un nom.
    """
    if not brut:
        return []
    paires = []
    for morceau in brut.split(b"\0"):
        if not morceau or b"=" not in morceau:
            continue
        nom, valeur = morceau.split(b"=", 1)
        nom = nom.decode("utf-8", "replace")
        if not NOM.match(nom):
            continue
        paires.append((nom, valeur.decode("utf-8", "replace")))
    return paires


def juger(nom: str, valeur: str) -> Variable:
    """Ce qu'on montre de cette variable. Fonction PURE.

    Trois issues : le secret, qui ne montre pas même sa longueur ; le nom
    permis dont la valeur a la forme attendue, qui s'affiche ; tout le reste,
    qui montre sa forme.
    """
    if SECRET.search(nom):
        return Variable(nom=nom, forme=MASQUE, secret=True)
    motif = PERMIS.get(nom)
    if motif and motif.match(valeur):
        return Variable(nom=nom, valeur=valeur, forme=valeur)
    return Variable(nom=nom, forme=_forme(valeur))


def variables(pid, *, ouvrir=None) -> list[Variable] | None:
    """Les variables d'un processus, jugées. None si rien n'est lisible."""
    brut = lire_environ(pid, ouvrir=ouvrir)
    if brut is None:
        return None
    return [juger(nom, valeur) for nom, valeur in decouper(brut)]


def devoile(pid, nom, *, ouvrir=None) -> str | None:
    """La valeur RÉELLE d'une variable nommée, sur demande explicite.

    Une seule à la fois, et jamais le bloc : c'est la soupape de la liste
    blanche, qui masque par construction toute variable neuve et utile. Rend
    None quand la variable n'existe pas ou que rien n'est lisible.
    """
    brut = lire_environ(pid, ouvrir=ouvrir)
    if brut is None:
        return None
    for cle, valeur in decouper(brut):
        if cle == nom:
            return valeur
    return None


def familles_absentes(liste) -> tuple[str, ...]:
    """Les familles attendues qu'aucune variable ne porte.

    L'écran le DIT plutôt que de laisser chercher : un utilisateur qui a posé
    `CLAUDE_CODE_ENABLE_TELEMETRY` et ne la voit pas ici n'a pas un écran
    cassé — il a un processus lancé avant, dont l'environnement est figé.
    """
    noms = {v.nom for v in liste or ()}
    return tuple(f for f in FAMILLES if not any(n.startswith(f) for n in noms))


def resume(liste) -> str:
    """« 27 · 11 · 16 · 1 » — total, en clair, masquées, secrètes.

    QUATRE nombres, parce que trois ne se réconciliaient pas : le troisième
    comptait les secrètes sous l'étiquette « masquées », et le lecteur d'un
    écran de diagnostic en déduisait qu'un reste était dans un état que
    personne ne nommait. Une variable masquée montre sa forme, une secrète ne
    montre même pas sa longueur — ce sont deux états, et les deux se disent.
    """
    if liste is None:
        return ""
    claires = sum(1 for v in liste if v.visible)
    secrets = sum(1 for v in liste if v.secret)
    masquees = sum(1 for v in liste if not v.visible)
    return f"{len(liste)} · {claires} · {masquees} · {secrets}"
