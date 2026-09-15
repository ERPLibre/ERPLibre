#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Installateurs amont des outils de développement.

Les mêmes outils se posent à DEUX endroits : sur l'hôte par le menu Shell,
et dans une VM par le déploiement QEMU. Une seule table les décrit, parce
que deux copies d'une URL dérivent dès que l'amont en change une, et que la
seconde copie est celle qu'on oublie.

Chacun est un installateur amont plutôt qu'un paquet : aucun n'est présent
dans les dépôts des quatre familles que supporte ERPLibre, et celui qui l'est
y traîne d'une version.
"""

# Proxy CLI qui réduit la consommation de tokens des assistants.
RTK_UPSTREAM = (
    "curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/"
    "refs/heads/master/install.sh | sh"
)

# L'installateur amont pose un binaire statique. Il sert de recours parce
# que le paquet manque d'une partie des dépôts des plateformes supportées.
STARSHIP_URL = "https://starship.rs/install.sh"

# « -f » n'est pas un ornement quand la sortie part dans un shell : sans lui,
# curl écrit le CORPS d'une réponse d'erreur et sort avec 0, si bien qu'une
# page HTML de 34 ko arrive sur l'entrée de « sh » et s'y interprète comme
# un script. Le diagnostic obtenu est alors « Syntax error » sur une ligne du
# HTML, qui ne dit ni que l'URL est fautive ni que rien n'a été installé.
# Avec « -f », curl n'écrit rien et rend 22. « -L » suit une redirection,
# qu'un projet amont pose sans prévenir.
STARSHIP_UPSTREAM = f"curl -fsSL {STARSHIP_URL} | sh"

# Sans terminal — une pose par SSH dans une VM — l'installateur demande une
# confirmation que personne ne donnera. « -y » la donne d'avance.
#
# Et il tourne en root. Sans droit d'écriture sur /usr/local/bin, son
# répertoire par défaut, l'installateur appelle « sudo -v » AVANT de
# télécharger quoi que ce soit. Or « sudo -v » exige un mot de passe dès
# qu'une seule règle sudoers qui vise le compte n'est pas NOPASSWD — celle
# du groupe d'administration ne l'est pas —, et sudo-rs ignore « verifypw »,
# le réglage qui l'en dispenserait. En root le répertoire est inscriptible :
# aucun « sudo -v » n'est atteint, et le binaire atterrit dans un répertoire
# que porte le PATH de tout compte, SSH non interactif compris.
#
# La borne de temps passe DERRIÈRE sudo. Un « timeout » lancé sans privilège
# ne peut pas tuer un installateur root : son signal au groupe de processus
# échoue en EPERM sur les processus root, et sudo ne relaie pas un signal
# venu de son propre groupe. Un « timeout » root, lui, tue l'installateur et
# ses enfants. Il reste en deçà de la borne extérieure de la pose, qui ne
# couvre plus que la moitié non privilégiée du tube : curl.
#
# « -k » : SIGTERM se laisse ignorer, et « timeout » seul attendrait alors
# sans fin. Passé ce délai, il envoie SIGKILL, qui ne s'ignore pas. Borne et
# délai additionnés restent sous la borne extérieure.
STARSHIP_ROOT_TIMEOUT = 280
STARSHIP_ROOT_KILL_AFTER = 10
STARSHIP_UPSTREAM_VM = (
    f"curl -fsSL {STARSHIP_URL}"
    f" | sudo timeout -k {STARSHIP_ROOT_KILL_AFTER}"
    f" {STARSHIP_ROOT_TIMEOUT} sh -s -- -y"
)

# Ce que chaque shell écrit pour lancer starship. La ligne va en FIN de
# fichier : starship compose le prompt et doit passer après tout ce qui y
# touche.
#
# bash et zsh la gardent par « command -v » : sans binaire — une pose qui a
# échoué, un binaire retiré depuis —, « eval "$(starship init …)" » écrirait
# « command not found » à l'ouverture de chaque shell. La garde est DANS la
# ligne, et non autour de son écriture : elle vaut aussi pour le binaire qui
# disparaît après coup. « starship init » y reste en clair, parce que c'est
# le motif qui dédoublonne, dans le menu de l'hôte comme dans la VM.
#
# Un « if » et non un « && » : la ligne est la DERNIÈRE du fichier, et le
# fichier rend son statut. « a && b » rend 1 quand starship manque, si bien
# qu'un script sous « set -e » qui lit ce fichier s'arrêterait là ; un « if »
# sans branche prise rend 0.
STARSHIP_LINE = {
    "bash": (
        "if command -v starship >/dev/null 2>&1; then"
        ' eval "$(starship init bash)"; fi'
    ),
    "zsh": (
        "if command -v starship >/dev/null 2>&1; then"
        ' eval "$(starship init zsh)"; fi'
    ),
    "fish": "starship init fish | source",
}

# Les assistants posés par un installateur amont : le nom du binaire mène
# à (commande, répertoire d'installation). Le répertoire sert à garantir
# le PATH — un binaire posé hors des chemins du shell reste introuvable.
AGENTS = {
    "claude": (
        "curl -fsSL https://claude.ai/install.sh | bash",
        "~/.local/bin",
    ),
    "opencode": (
        "curl -fsSL https://opencode.ai/install | bash",
        "~/.opencode/bin",
    ),
}

# L'agent posé quand rien n'est choisi. Le premier de la table ferait
# dépendre le défaut de l'ordre d'écriture d'un dictionnaire.
AGENT_DEFAUT = "claude"
