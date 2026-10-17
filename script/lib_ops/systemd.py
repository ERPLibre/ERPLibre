# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Lire une unité systemd, l'arrêter, la démarrer, lire son journal.

Ce module ne crée, ne modifie ni ne supprime aucune unité : il lit ce que
`systemctl show` en dit et passe par `systemctl stop` / `start` /
`is-active`. Le contenu de l'unité reste l'affaire de qui l'a installée.

Chaque fonction reçoit un `lanceur` : `lanceur(argv, timeout) -> (code,
sortie)`, qui ne lève jamais. Par défaut c'est `lancer`, qui exécute
vraiment ; un test passe le sien et aucun systemctl réel n'est appelé.

Bibliothèque standard seulement.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess

# Nom d'unité admis : ce que systemd accepte, sans rien qu'un shell
# interpréterait.
RE_NOM_UNITE = re.compile(r"[A-Za-z0-9@_.:-]+")

# Unités candidates à l'auto-détection : celles qu'ERPLibre ou un paquet
# Odoo installent.
RE_CANDIDATE = re.compile(r"(erplibre|odoo)[A-Za-z0-9@_.:-]*\.service")

PROPRIETES = (
    "LoadState",
    "ActiveState",
    "User",
    "WorkingDirectory",
    "ExecStart",
    "Environment",
)

# Les ActiveState d'une unité dont plus aucun processus ne tourne.
ETATS_ARRETES = ("inactive", "failed")


class ErreurUnite(Exception):
    """L'unité ne peut pas être déterminée ou lue. Rien n'a été arrêté.

    `candidates` porte les noms entre lesquels le choix n'a pas pu se
    faire, pour que le message les cite.
    """

    def __init__(self, message, candidates=()):
        super().__init__(message)
        self.candidates = list(candidates)


def lancer(argv, timeout=60):
    """Exécute `argv` et rend (code, sortie). Ne lève jamais.

    La sortie est stdout ; stderr s'y ajoute seulement quand le code est
    non nul, pour que le message d'erreur reste lisible sans polluer ce
    que l'appelant analyse (`KEY=VALUE` de `systemctl show`). Un binaire
    absent rend 127, un délai dépassé 124.
    """
    try:
        fin = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except OSError as err:
        return 127, str(err)
    sortie = fin.stdout or ""
    if fin.returncode != 0 and fin.stderr:
        sortie += fin.stderr
    return fin.returncode, sortie


def nom_unite(nom):
    """Le nom complet de l'unité : `.service` ajouté à un nom sans point.

    ValueError sur un nom vide ou hors de `RE_NOM_UNITE`.
    """
    nom = (nom or "").strip()
    if not nom or RE_NOM_UNITE.fullmatch(nom) is None:
        raise ValueError(nom)
    if "." not in nom:
        nom += ".service"
    return nom


def lire_proprietes(unite, noms=PROPRIETES, lanceur=lancer):
    """Les propriétés `noms` de l'unité, en dict {nom: valeur}.

    Une propriété absente de la sortie vaut "". ErreurUnite si systemctl
    ne répond pas.
    """
    argv = ["systemctl", "show"]
    for nom in noms:
        argv += ["-p", nom]
    argv += ["--", unite]
    code, sortie = lanceur(argv, 30)
    if code != 0:
        raise ErreurUnite(sortie.strip() or f"systemctl show {unite}")
    valeurs = {nom: "" for nom in noms}
    for ligne in sortie.splitlines():
        cle, egal, valeur = ligne.partition("=")
        if egal and cle in valeurs:
            valeurs[cle] = valeur
    return valeurs


def _decouper(texte):
    """shlex.split, avec repli sur un découpage aux espaces quand les
    guillemets ne s'équilibrent pas."""
    try:
        return shlex.split(texte)
    except ValueError:
        return texte.split()


def argv_execstart(valeur):
    """Le premier `argv[]=` de la propriété ExecStart, en liste.

    systemctl le présente sous la forme
    `{ path=/bin/bash ; argv[]=/bin/bash /x/run.sh -d base ; ignore… }`.
    Une valeur vide rend [].
    """
    debut = valeur.find("argv[]=")
    if debut < 0:
        return []
    reste = valeur[debut + len("argv[]=") :]
    fin = reste.find(" ;")
    if fin >= 0:
        reste = reste[:fin]
    return _decouper(reste.strip())


def environnement(valeur):
    """La propriété Environment en dict {nom: valeur}.

    Les affectations sont séparées par des espaces ; systemd met entre
    guillemets celles qui en contiennent.
    """
    resultat = {}
    for morceau in _decouper(valeur or ""):
        nom, egal, val = morceau.partition("=")
        if egal and nom:
            resultat[nom] = val
    return resultat


def dossier_de_travail(valeur, home=None):
    """WorkingDirectory sans ses préfixes systemd.

    `-` (ignorer s'il manque) est retiré ; `~` désigne le dossier personnel
    de l'utilisateur de l'unité, passé dans `home`. Rend "" si la valeur
    est vide ou ne se résout pas.
    """
    valeur = (valeur or "").strip()
    if valeur.startswith(("-", "!")):
        valeur = valeur[1:]
    if valeur == "~":
        return home or ""
    return valeur


def lister_unites(lanceur=lancer):
    """[(nom, actif)] de toutes les unités de service connues."""
    code, sortie = lanceur(
        [
            "systemctl",
            "list-units",
            "--type=service",
            "--all",
            "--no-legend",
            "--plain",
        ],
        30,
    )
    if code != 0:
        return []
    unites = []
    for ligne in sortie.splitlines():
        colonnes = ligne.replace("●", " ").split()
        if len(colonnes) >= 3:
            unites.append((colonnes[0], colonnes[2] == "active"))
    return unites


def deviner_unite(racine, lanceur=lancer):
    """L'unité qui fait tourner ce checkout : (nom, raison).

    Les candidates sont les unités `erplibre…` / `odoo…`. On retient
    d'abord celles dont WorkingDirectory est `racine` ; à défaut, la seule
    active. `raison` vaut "workdir" ou "active".

    ErreurUnite si aucune candidate ne convient, ou si plusieurs restent
    à égalité — `candidates` les nomme.
    """
    candidates = [
        (nom, actif)
        for nom, actif in lister_unites(lanceur)
        if RE_CANDIDATE.fullmatch(nom)
    ]
    if not candidates:
        raise ErreurUnite("no candidate")
    cible = os.path.realpath(racine)
    ici = []
    for nom, actif in candidates:
        try:
            wd = lire_proprietes(nom, ("WorkingDirectory",), lanceur)
        except ErreurUnite:
            continue
        dossier = dossier_de_travail(wd["WorkingDirectory"])
        if dossier and os.path.realpath(dossier) == cible:
            ici.append((nom, actif))
    if len(ici) == 1:
        return ici[0][0], "workdir"
    if ici:
        actives = [nom for nom, actif in ici if actif]
        if len(actives) == 1:
            return actives[0], "workdir"
        raise ErreurUnite("ambiguous", [nom for nom, _ in ici])
    actives = [nom for nom, actif in candidates if actif]
    if len(actives) == 1:
        return actives[0], "active"
    raise ErreurUnite(
        "ambiguous" if actives else "none active",
        actives or [nom for nom, _ in candidates],
    )


def est_actif(unite, lanceur=lancer):
    """True si `systemctl is-active` répond `active`."""
    _code, sortie = lanceur(["systemctl", "is-active", "--", unite], 30)
    return sortie.strip().splitlines()[:1] == ["active"]


def etat(unite, lanceur=lancer):
    """L'ActiveState de l'unité (`active`, `inactive`, `failed`,
    `activating`, `deactivating`, `reloading`…), ou "" quand systemctl ne
    donne pas de réponse exploitable — délai dépassé, code non nul, sortie
    vide. "" se lit « état inconnu », jamais « arrêté »."""
    try:
        valeurs = lire_proprietes(unite, ("ActiveState",), lanceur)
    except ErreurUnite:
        return ""
    return valeurs["ActiveState"].strip()


def est_arrete(valeur):
    """True si l'ActiveState `valeur` dit l'unité arrêtée pour de bon :
    `inactive` ou `failed`. `deactivating` ne l'est pas encore."""
    return valeur in ETATS_ARRETES


def arreter(unite, lanceur=lancer, timeout=300):
    """`systemctl stop` ; rend (code, sortie)."""
    return lanceur(["systemctl", "stop", "--", unite], timeout)


def demarrer(unite, lanceur=lancer, timeout=300):
    """`systemctl start` ; rend (code, sortie)."""
    return lanceur(["systemctl", "start", "--", unite], timeout)


def journal_depuis(unite, epoque, lanceur=lancer):
    """Les lignes du journal de l'unité depuis `epoque` (secondes Unix).

    `-o cat` rend le message brut, tel qu'Odoo l'a écrit, ce qui permet de
    lui appliquer le même filtre qu'à un fichier de journal. Rend "" si
    journalctl ne répond pas.
    """
    code, sortie = lanceur(
        [
            "journalctl",
            "-u",
            unite,
            "--since",
            f"@{int(epoque)}",
            "-o",
            "cat",
            "--no-pager",
        ],
        60,
    )
    return sortie if code == 0 else ""
