#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'adaptateur de Claude Code : les argv de ses agents d'arrière-plan.

Un agent d'arrière-plan est un processus détaché qui continue sans terminal.
Cinq sous-commandes le pilotent, et elles ne se valent pas du tout :

| Sous-commande | Ce qu'elle fait | Ce qu'elle coûte si on se trompe |
|---|---|---|
| `logs` | imprime la sortie récente | rien, elle lit |
| `attach` | ouvre la session dans ce terminal | rien, la session continue |
| `stop` | l'arrête, la conversation est GARDÉE | un `attach` la rouvre |
| `respawn` | la redémarre sur le binaire courant | le travail en cours est coupé |
| `rm` | supprime la session ET son arbre de travail | rien ne la récupère |

`rm` est donc la seule qui exige de retaper l'identifiant en entier, comme la
suppression d'un serveur exige de retaper son nom : une frappe sur « o » se
donne par réflexe, recopier un identifiant oblige à regarder ce qu'on détruit.

`--discard-unpushed` n'est JAMAIS construit ici. Le drapeau jette les commits
non poussés d'un arbre de travail, et le CLI n'accepte que la valeur qu'un
`claude rm` précédent rapporte lui-même — un menu qui la fabriquerait
détruirait du travail sur une valeur devinée. Le menu montre ce que `rm` a
rapporté et s'arrête là.

**L'identifiant est COURT, et c'est le piège du module.** Le listage porte
deux champs d'identité pour un agent détaché : `id`, huit caractères, et
`sessionId`, l'UUID complet. Les cinq sous-commandes n'acceptent que le
premier. Passer l'UUID rend « No job matching », et le rend avec un code de
sortie NUL : aucun appelant ne voit l'action échouer, l'écran annonce un
geste qui n'a pas eu lieu. Une session interactive ne porte pas `id` du tout,
ce qui est cohérent — les cinq sous-commandes ne s'appliquent qu'aux
détachées.

**Ce que ce module ne construit pas.** Le lancement d'un agent détaché n'est
pas ici. `claude --bg` accepte son invite sur l'entrée standard et imprime
l'identifiant court : la contrainte du dépôt — une invite ne passe jamais par
l'argv, où `/proc/<pid>/cmdline` la rend lisible par tout compte de la machine
— est donc tenable. Ce qui manque est ailleurs : un agent détaché ouvre un
arbre de travail que `rm` supprime, et le menu n'a pas encore de quoi dire à
l'utilisateur ce qu'il engage.
"""
from __future__ import annotations

# Les sous-commandes, nommées pour que l'appelant ne les épelle pas.
JOURNAL = "logs"
ATTACHER = "attach"
ARRETER = "stop"
RELANCER = "respawn"
SUPPRIMER = "rm"

# Celles qui coupent ou détruisent. Le menu confirme avant.
DESTRUCTRICES = (RELANCER, SUPPRIMER)

# Celle qui ne se répare pas. Elle exige l'identifiant retapé en entier.
IRREVERSIBLE = SUPPRIMER


def argv_lister(*, terminees=False) -> list[str]:
    """L'argv qui liste les sessions, en JSON et sans exiger de terminal.

    `terminees` ajoute `--all`, qui inclut les sessions d'arrière-plan déjà
    sorties : ce sont celles que `rm` peut encore nettoyer, et les taire
    laisserait un arbre de travail que rien ne propose de retirer.
    """
    argv = ["claude", "agents", "--json"]
    if terminees:
        argv.append("--all")
    return argv


def argv_action(sous_commande: str, session_id: str) -> list[str]:
    """L'argv d'une action sur UNE session d'arrière-plan.

    Rend une liste de trois éléments et rien de plus : aucun drapeau ne
    s'ajoute ici, et surtout pas `--discard-unpushed`.
    """
    if sous_commande not in (
        JOURNAL,
        ATTACHER,
        ARRETER,
        RELANCER,
        SUPPRIMER,
    ):
        raise ValueError(f"sous-commande inconnue : {sous_commande}")
    if not session_id:
        raise ValueError("un identifiant de session est exigé")
    return ["claude", sous_commande, str(session_id)]


def est_arriere_plan(session) -> bool:
    """Vrai si cette session est un agent détaché et non un terminal.

    Le registre rend `kind`, et le binaire en connaît cinq valeurs —
    interactive, background, detached, remote, cloud. Tout ce qui n'est pas
    interactif est piloté par les cinq sous-commandes ; un terminal, lui, se
    reprend par `--resume` et se questionne par une copie branchée.
    """
    return getattr(session, "kind", "") != "interactive"


def confirmation_exigee(sous_commande: str) -> str:
    """Ce que le menu doit obtenir avant d'agir : « rien », « oui », « id ».

    Trois niveaux, et l'écart entre les deux derniers est ce qui compte : une
    frappe sur « o » se donne par réflexe, et recopier un identifiant oblige à
    regarder ce qu'on détruit.
    """
    if sous_commande == IRREVERSIBLE:
        return "id"
    if sous_commande in DESTRUCTRICES:
        return "oui"
    return "rien"
