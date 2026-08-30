#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le message d'un commit tient-il la convention ?

La convention est dans `.claude/rules/04-code-conventions.md`, son mode
d'emploi dans `conf/template_claude_commands_commit.md`. Ce module en vérifie
la part MÉCANIQUE, sur deux plans :

- le sujet : le tag, la longueur, l'ouverture sur une citation ;
- le corps : sa longueur par langue, et la donnée identifiante.

Le reste — « ce sujet dit-il sur quoi porte le code », « ce corps raconte-t-il
l'enquête plutôt que le fonctionnement » — est un jugement, et aucun hook ne
le rendra.

Compté en CARACTÈRES et non en octets : « préchauffer » pèse 11 caractères et
12 octets, et une limite en octets refuserait des sujets français conformes.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib_identifiant import (  # noqa: E402
    NOMS_INTERDITS,
    identifiants,
    termes_interdits,
)

MAX = 72

# Lignes non vides par langue. Le corps est bilingue : ce budget est celui
# d'UNE des deux moitiés, pas du message entier.
MAX_BODY = 10

TAGS = ("ADD", "FIX", "UPD", "IMP", "REF", "REM", "MOV", "I18N")

# Ce que git écrit lui-même, ou ce qu'un rebase consomme : hors convention.
GENERATED = ("Merge ", "Revert ", "fixup!", "squash!", "amend!")

# Un sujet qui s'ouvre sur une citation cite un écran. C'est une PREUVE, et une
# preuve va dans le corps — le sujet doit nommer la cause.
QUOTES = ("«", '"', "'", "`", "“", "‘")

# Le marqueur nomme la langue de ce qui SUIT : il sépare les deux moitiés.
MARKER = re.compile(r"^---\s*(FR|EN)\s*---\s*$", re.MULTILINE)

# `git commit --cleanup=scissors` laisse le diff en clair sous cette ligne :
# tout ce qui suit appartient à git, pas à l'auteur.
CISEAUX = re.compile(r"^#?\s*-{2,}\s*>8\s*-{2,}")

# Un trailer porte légitimement une adresse, et `-x` ajoute sa propre ligne.
# La liste est fermée : « Checked: … » reste du corps et se fait vérifier.
TRAILER = re.compile(
    r"^(?:Assisted-by|Co-authored-by|Signed-off-by|Reviewed-by|Acked-by"
    r"|Tested-by|Reported-by|Suggested-by|Cc|Fixes|Closes|Refs|Link):\s"
    r"|^\(cherry picked from commit [0-9a-f]+\)$",
    re.IGNORECASE,
)


def subject_of(message: str) -> str:
    """La première ligne utile : ni commentaire, ni ligne vide."""
    for line in message.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped
    return ""


def _apres_le_sujet(message: str) -> list:
    """Les lignes du corps : ni commentaire, ni diff de `--verbose`."""
    lines = message.split("\n")
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines = lines[index + 1 :]
            break
    else:
        return []

    gardees = []
    for line in lines:
        stripped = line.strip()
        if CISEAUX.match(stripped):
            break
        if stripped.startswith("#"):
            continue
        gardees.append(line)
    return gardees


def body_of(message: str, trailers: bool = False) -> str:
    """Ce qui suit le sujet, sans les lignes que git ajoute ou qu'il ignore.

    Sans `trailers`, les lignes `Assisted-by:` et consorts sont retirées : le
    budget de lignes ne les compte pas, et l'adresse d'un `Co-authored-by:` est
    légitime. Avec, elles restent — un nom de client logé dans un `Refs:` est
    tout aussi publié que dans une phrase.
    """
    gardees = _apres_le_sujet(message)
    if not trailers:
        gardees = [
            ligne for ligne in gardees if not TRAILER.match(ligne.strip())
        ]
    return "\n".join(gardees)


def _moities(body: str) -> list:
    """Le corps découpé par le marqueur de langue. Une seule moitié sans lui."""
    return [part for part in MARKER.split(body) if part not in ("FR", "EN")]


def _check_subject(subject: str) -> list:
    problems = []

    tag = None
    for candidate in TAGS:
        if subject.startswith(f"[{candidate}]"):
            tag = candidate
            break
    if tag is None:
        problems.append(
            f"le sujet doit commencer par un tag : {', '.join('[%s]' % t for t in TAGS)}"
        )

    if len(subject) > MAX:
        problems.append(
            f"le sujet fait {len(subject)} caractères, {MAX} au plus.\n"
            "     Ne le tronquez pas : à cette longueur, écrivez des MOTS-CLÉS\n"
            "     qui résument plutôt qu'une phrase amputée. « proxmox : pmxcfs,\n"
            "     stockage, diagnostic » vaut mieux qu'une phrase coupée net."
        )

    rest = subject.split(":", 1)[1].strip() if ":" in subject else ""
    if rest.startswith(QUOTES):
        problems.append(
            "le sujet s'ouvre sur une citation. Un message d'écran est une\n"
            "     preuve : elle va dans le corps. Le sujet nomme la cause."
        )

    return problems


def _check_body(sans_trailers: str, avec_trailers: str) -> list:
    """Longueur par langue et donnée identifiante. Rien sur le style.

    Le budget de lignes et le courriel se jugent SANS les trailers, qui sont
    de git et portent légitimement une adresse. L'adresse IP, le chemin de
    compte et le nom privé se jugent AVEC : un `Refs:` publie autant.
    """
    problems = []

    for moitie in _moities(sans_trailers):
        pleines = [ligne for ligne in moitie.split("\n") if ligne.strip()]
        if len(pleines) > MAX_BODY:
            problems.append(
                f"le corps fait {len(pleines)} lignes pour une langue,"
                f" {MAX_BODY} au plus.\n"
                "     Le corps dit pourquoi c'était nécessaire, puis s'arrête.\n"
                "     L'enquête, les mesures datées et les impasses vont dans\n"
                "     tasks/, qui n'est pas versionné."
            )
            break

    termes = termes_interdits(NOMS_INTERDITS)
    par_motif = {}
    for motif, extrait, _ in identifiants(avec_trailers, termes):
        if motif != "courriel":
            par_motif.setdefault(motif, []).append(extrait)
    for motif, extrait, _ in identifiants(sans_trailers, ()):
        if motif == "courriel":
            par_motif.setdefault(motif, []).append(extrait)

    adresses = sorted(set(par_motif.get("adresse", [])))
    if adresses:
        problems.append(
            f"le corps porte une adresse IP : {', '.join(adresses)}.\n"
            "     Une adresse désigne une machine. Nommez la CLASSE de\n"
            "     situation — « sur un hôte derrière un NAT » — pas la machine."
        )

    courriels = sorted(set(par_motif.get("courriel", [])))
    if courriels:
        problems.append(
            f"le corps porte une adresse de courriel : {', '.join(courriels)}."
        )

    comptes = sorted(set(par_motif.get("compte", [])))
    if comptes:
        problems.append(
            f"le corps porte un chemin de compte : {comptes[0]}….\n"
            "     Écrivez ~/ ou /home/<utilisateur>/."
        )

    noms = sorted(set(par_motif.get("nom privé", [])))
    if noms:
        problems.append(
            f"le corps porte un nom refusé : {', '.join(noms)}.\n"
            "     Généralisez — « sur une base de production » — ou retirez la\n"
            "     phrase."
        )

    return problems


def check(message: str) -> list:
    """Rend la liste des problèmes. Vide si le message passe."""
    subject = subject_of(message)
    if not subject or subject.startswith(GENERATED):
        return []
    return _check_subject(subject) + _check_body(
        body_of(message), body_of(message, trailers=True)
    )
