#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'adaptateur d'Open Code : ses séances, et ce qu'elles ont coûté.

Le harnais ressemble à Claude Code de loin et en diffère sur trois points qui
décident de la forme de tout écran bâti dessus.

**Le listage est cadré sur le RÉPERTOIRE COURANT.** `opencode session list`
rend les séances ouvertes là où on le lance, et rien d'autre : lancé à la
racine d'un dépôt, il ne voit pas celles d'un autre. Là où `claude agents`
répond « ce qui tourne sur cette machine », celui-ci répond « ce qui s'est
passé ICI ». Aucun drapeau n'élargit la portée — le listage n'accepte que
`--format` et `-n`. Un écran qui présenterait les deux comme la même question
annoncerait « aucune séance » à qui en a vingt dans le répertoire d'à côté.

**Le titre d'une séance est ENGENDRÉ par le modèle** à partir de la
conversation. Il a la forme d'un champ structurel et n'en est pas un : c'est
du contenu d'utilisateur résumé. Il ne sort donc pas de ce module, exactement
comme le titre d'une session de Claude Code n'en sort pas. Ce qui situe une
séance sans la citer est ailleurs : son identifiant, son répertoire, ses
dates.

**Rien de ce qui dépense ou détruit n'est construit ici.** `run` lance une
vraie conversation, et une conversation d'Open Code écrit dans l'arbre de
travail SANS demander — une consigne de trois mots suffit à faire créer un
fichier. `delete`, `uninstall` et `upgrade` changent l'installation. Une
entrée de menu nommée « question libre » qui crée des fichiers est un piège,
donc l'adaptateur ne déclare que la LECTURE, et les autres commandes restent
au CLI, où l'on va exprès. C'est la même règle que pour les serveurs MCP.

Deux formes de sortie piègent le décodage :

- Un listage VIDE n'est pas `[]`, c'est une sortie vide, que `json.loads`
  refuse. Une installation neuve, ou un répertoire sans séance, rend donc
  quelque chose qui lève si on le décode sans regarder.
- `export` imprime son préambule — « Exporting session: … » — sur la sortie
  d'ERREUR, et son JSON sur la sortie standard. Les fusionner, ce que fait
  `2>&1`, met la ligne devant le JSON et le rend indécodable ; le décodage
  part donc de la première accolade, ce qui vaut dans les deux cas.
- **`export` TRONQUE sa propre sortie quand elle est longue.** Il sort avant
  d'avoir vidé son tampon : trois exécutions du même export rendent 65 536,
  98 304 et 110 768 octets, toutes coupées au milieu d'une chaîne. En dessous
  d'une soixantaine de kilooctets la sortie est entière et reproductible ;
  au-dessus, aucune ne l'est, et réessayer n'y change rien. Le décodage rend
  donc None, et `semble_tronque` distingue cette panne-là d'une sortie vide —
  l'écran peut ainsi dire que l'outil a coupé, plutôt que de laisser croire à
  une séance illisible ou gratuite.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

# Le binaire, et le répertoire qui porte sa base et ses identifiants. Les
# quatre répertoires qu'il crée ne se valent pas : celui-ci est le seul dont
# la présence dit qu'il a tourné, les autres n'ayant qu'un cache ou un schéma.
BINAIRE = "opencode"
MAISON = "~/.local/share/opencode"

# La forme d'un identifiant de séance. Close, parce qu'il finit dans une ligne
# de shell : tout ce qui n'est pas ici est refusé plutôt qu'échappé.
IDENTIFIANT = re.compile(r"^ses_[A-Za-z0-9]{8,64}$")


@dataclass(frozen=True)
class Seance:
    """Une séance, réduite à ce qui la situe.

    Sans son titre : il est engendré par le modèle à partir de la
    conversation, donc c'est du contenu résumé et non un champ structurel.
    """

    identifiant: str
    repertoire: str = ""
    projet: str = ""
    cree: int = 0
    modifie: int = 0

    @property
    def quand(self) -> str:
        """Le moment de la dernière écriture, ou "" s'il n'est pas porté.

        En absolu et non en « il y a deux heures » : le français met ce
        tour-là devant et l'anglais derrière, et un écran bâti sur une seule
        des deux places se lit de travers dans l'autre langue.

        Sans ce champ, deux séances du même répertoire sont INDISCERNABLES à
        l'écran — le titre étant du contenu, il ne sort pas, et le répertoire
        vaut toujours celui d'où l'on a listé.
        """
        if not self.modifie:
            return ""
        return time.strftime(
            "%Y-%m-%d %H:%M", time.localtime(self.modifie / 1000)
        )


@dataclass(frozen=True)
class Resume:
    """Ce qu'une séance a coûté, tel que son export le porte.

    Les champs répondent un pour un à ceux d'une transcription de Claude Code
    — coût, jetons, lignes touchées — ce qui permet aux deux harnais de
    nourrir le même écran sans que celui-ci sache lequel il regarde.
    """

    identifiant: str = ""
    modele: str = ""
    fournisseur: str = ""
    agent: str = ""
    version: str = ""
    cout: float = 0.0
    entree: int = 0
    sortie: int = 0
    raisonnement: int = 0
    cache_lu: int = 0
    cache_ecrit: int = 0
    lignes_ajoutees: int = 0
    lignes_retirees: int = 0
    fichiers: int = 0

    @property
    def jetons(self) -> int:
        """Ce qui a traversé le modèle, cache compris.

        Le cache LU compte : il est facturé, moins cher, et l'ignorer fait
        annoncer une fraction de ce qui a réellement circulé.
        """
        return (
            self.entree
            + self.sortie
            + self.raisonnement
            + self.cache_lu
            + self.cache_ecrit
        )


def _compte(valeur, quoi: str) -> int:
    """Un entier strictement positif, ou une erreur. Fonction PURE.

    Le booléen est rejeté explicitement : `isinstance(True, int)` est vrai en
    Python, donc un drapeau passé par erreur se glisserait dans l'argv et y
    deviendrait « True », que l'outil refuse bien plus loin et bien moins
    clairement.
    """
    if isinstance(valeur, bool) or not isinstance(valeur, int) or valeur < 1:
        raise ValueError(f"{quoi} refusé : {valeur!r}")
    return valeur


def argv_lister(*, maximum=None) -> list[str]:
    """L'argv qui liste les séances DU RÉPERTOIRE COURANT, en JSON.

    `maximum` borne aux N plus récentes. Il n'existe aucun drapeau qui
    élargirait la portée au-delà du répertoire : c'est une propriété de
    l'outil, pas un oubli d'ici.
    """
    argv = [BINAIRE, "session", "list", "--format", "json"]
    if maximum is not None:
        argv += ["-n", str(_compte(maximum, "maximum"))]
    return argv


def argv_exporter(identifiant: str) -> list[str]:
    """L'argv qui exporte UNE séance. Lecture seule.

    L'identifiant est vérifié ici, contre une forme close, parce que
    l'appelant le recolle en une ligne de shell.
    """
    if not identifiant or not IDENTIFIANT.match(identifiant):
        raise ValueError(f"identifiant de séance refusé : {identifiant!r}")
    return [BINAIRE, "export", identifiant]


def argv_statistiques(*, jours=None) -> list[str]:
    """L'argv des statistiques, par outil et par modèle.

    Contrairement au listage, elles portent sur TOUS les projets par défaut.
    Leur sortie est un tableau encadré et non du JSON : elle se montre, elle
    ne se décode pas — d'où l'absence de décodeur dans ce module.
    """
    argv = [BINAIRE, "stats", "--tools", "10", "--models"]
    if jours is not None:
        argv += ["--days", str(_compte(jours, "nombre de jours"))]
    return argv


def _entier(valeur) -> int:
    """Un entier, ou zéro. Un champ absent ne doit pas lever."""
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return 0
    return int(valeur)


def _reel(valeur) -> float:
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return 0.0
    return float(valeur)


def _texte(valeur) -> str:
    return valeur if isinstance(valeur, str) else ""


def decoder_liste(texte) -> list[Seance]:
    """Les séances d'un listage JSON. Fonction PURE.

    Une sortie VIDE rend une liste vide et ne lève pas : c'est ce que l'outil
    imprime quand le répertoire n'a aucune séance, et `json.loads` refuse la
    chaîne vide. Confondre « rien à décoder » avec « décodage impossible »
    ferait passer une installation neuve pour une panne.
    """
    if not texte or not texte.strip():
        return []
    try:
        charge = json.loads(texte)
    except ValueError:
        return []
    if not isinstance(charge, list):
        return []
    seances = []
    for brute in charge:
        if not isinstance(brute, dict):
            continue
        identifiant = _texte(brute.get("id"))
        if not identifiant:
            continue
        seances.append(
            Seance(
                identifiant=identifiant,
                repertoire=_texte(brute.get("directory")),
                projet=_texte(brute.get("projectId")),
                cree=_entier(brute.get("created")),
                modifie=_entier(brute.get("updated")),
            )
        )
    return seances


def semble_tronque(texte) -> bool:
    """Cette sortie a-t-elle COMMENCÉ un JSON sans le finir ? Fonction PURE.

    C'est la signature de la panne d'`export` sur une longue séance : l'outil
    sort avant d'avoir vidé son tampon, et la sortie s'arrête au milieu. La
    distinguer d'une sortie vide change ce que l'écran a le droit de dire —
    « l'outil a coupé », et non « cette séance est illisible ».
    """
    if not texte:
        return False
    debut = texte.find("{")
    if debut < 0:
        return False
    try:
        json.loads(texte[debut:])
    except ValueError:
        return True
    return False


def decoder_export(texte) -> Resume | None:
    """Ce qu'un export dit du coût d'une séance. Fonction PURE.

    Le décodage commence à la PREMIÈRE accolade : l'outil imprime une ligne de
    préambule avant son JSON, et décoder la sortie entière lève. Rend None
    quand rien n'est décodable, ce qui n'est pas un résumé à zéro.
    """
    if not texte:
        return None
    debut = texte.find("{")
    if debut < 0:
        return None
    try:
        charge = json.loads(texte[debut:])
    except ValueError:
        return None
    if not isinstance(charge, dict):
        return None
    info = charge.get("info")
    if not isinstance(info, dict):
        return None
    modele = info.get("model")
    modele = modele if isinstance(modele, dict) else {}
    jetons = info.get("tokens")
    jetons = jetons if isinstance(jetons, dict) else {}
    cache = jetons.get("cache")
    cache = cache if isinstance(cache, dict) else {}
    resume = info.get("summary")
    resume = resume if isinstance(resume, dict) else {}
    return Resume(
        identifiant=_texte(info.get("id")),
        modele=_texte(modele.get("id")),
        fournisseur=_texte(modele.get("providerID")),
        agent=_texte(info.get("agent")),
        version=_texte(info.get("version")),
        cout=_reel(info.get("cost")),
        entree=_entier(jetons.get("input")),
        sortie=_entier(jetons.get("output")),
        raisonnement=_entier(jetons.get("reasoning")),
        cache_lu=_entier(cache.get("read")),
        cache_ecrit=_entier(cache.get("write")),
        lignes_ajoutees=_entier(resume.get("additions")),
        lignes_retirees=_entier(resume.get("deletions")),
        fichiers=_entier(resume.get("files")),
    )
