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
STARSHIP_UPSTREAM_YES = f"curl -fsSL {STARSHIP_URL} | sh -s -- -y"

# Ce que chaque shell écrit pour lancer starship. La ligne va en FIN de
# fichier : starship compose le prompt et doit passer après tout ce qui y
# touche.
STARSHIP_LINE = {
    "bash": 'eval "$(starship init bash)"',
    "zsh": 'eval "$(starship init zsh)"',
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
