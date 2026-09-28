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

**Le lancement passe par l'ENTRÉE STANDARD.** `claude --bg` accepte son invite
ainsi et imprime l'identifiant court. La contrainte du dépôt est donc tenue
sans effort : une invite ne passe jamais par l'argv, où `/proc/<pid>/cmdline`
la rend lisible par tout compte de la machine. Aucun drapeau n'est fabriqué
autour — ni modèle, ni effort, ni saut de permissions : un écran qui les
choisirait déciderait à la place de l'utilisateur, sur des valeurs qu'il n'a
pas vues.

**Le genre peut être VIDE, et ce n'est pas « détaché ».** Le registre annonce
`interactive` pour un terminal et un genre d'arrière-plan pour un agent, mais
la flotte réunit une seconde source : un balayage des transcriptions, qui
annonce ce qui se REPREND. Une session dormante en sort sans genre ni
processus. `est_arriere_plan` ne tranche donc que le genre, et l'appelant
exige la VIVACITÉ en plus — sans quoi il proposerait `stop` sur un fichier,
et l'outil répondrait « No job matching » avec un code de sortie nul.
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


def argv_lancer() -> list[str]:
    """L'argv qui lance un agent détaché. L'invite passe par l'ENTRÉE STANDARD.

    Jamais en positionnel : `/proc/<pid>/cmdline` est lisible par tout compte
    de la machine, là où l'entrée standard ne l'est pas. La mesure confirme
    que l'outil l'accepte ainsi et imprime l'identifiant court sur sa sortie.

    Rend une liste de deux éléments et rien de plus. Aucun drapeau ne s'ajoute
    ici — ni `--dangerously-skip-permissions`, ni un modèle, ni un effort : un
    écran qui les fabriquerait déciderait à la place de l'utilisateur, sur des
    valeurs qu'il n'a pas vues.
    """
    return ["claude", "--bg"]


def identifiant_lance(sortie: str) -> str:
    """L'identifiant court qu'un lancement vient d'imprimer, ou "".

    L'outil annonce « backgrounded · <id> » puis les commandes qui le
    prennent. On lit la PREMIÈRE forme d'identifiant rencontrée, et rien
    d'autre : le reste de la sortie répète l'identifiant dans des phrases que
    la moindre reformulation changerait.
    """
    for mot in (sortie or "").replace("\u00b7", " ").split():
        net = mot.strip(".,;:()[]")
        if len(net) == 8 and all(c in "0123456789abcdef" for c in net):
            return net
    return ""


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

    Le genre VIDE d'une session dormante passe donc ici pour « détaché », et
    c'est voulu : cette fonction ne connaît que le genre. La vivacité est la
    seconde moitié de la question, et l'appelant l'exige — les deux séparées,
    chacune se vérifie.
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
