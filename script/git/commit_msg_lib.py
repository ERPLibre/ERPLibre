#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le sujet d'un commit tient-il la convention ?

La convention est dans `.claude/rules/04-code-conventions.md`, son mode
d'emploi dans `conf/template_claude_commands_commit.md`. Ce module en vérifie
la part MÉCANIQUE : le tag, la longueur, et le sujet qui s'ouvre sur une
citation. Le reste — « ce sujet dit-il sur quoi porte le code » — est un
jugement, et aucun hook ne le rendra.

Compté en CARACTÈRES et non en octets : « préchauffer » pèse 12 caractères et
14 octets, et une limite en octets refuserait des sujets français conformes.
"""

MAX = 72

TAGS = ("ADD", "FIX", "UPD", "IMP", "REF", "REM", "MOV", "I18N")

# Ce que git écrit lui-même, ou ce qu'un rebase consomme : hors convention.
GENERATED = ("Merge ", "Revert ", "fixup!", "squash!", "amend!")

# Un sujet qui s'ouvre sur une citation cite un écran. C'est une PREUVE, et une
# preuve va dans le corps — le sujet doit nommer la cause.
QUOTES = ("«", '"', "'", "`", "“", "‘")


def subject_of(message: str) -> str:
    """La première ligne utile : ni commentaire, ni ligne vide."""
    for line in message.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped
    return ""


def check(message: str) -> list:
    """Rend la liste des problèmes. Vide si le sujet passe."""
    subject = subject_of(message)
    if not subject or subject.startswith(GENERATED):
        return []

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
