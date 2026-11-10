# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque sourcée par les passations à repo sync de script/manifest/
# (streamdeck_games_to_repo.sh, erplibre_home_extension_to_repo.sh) : ce
# qu'elles lisent d'un dépôt à part qu'un checkout reçoit soit par repo
# sync, soit par un « git clone » ordinaire d'install_erplibre_home.sh. Elle
# ne pose que des fonctions et ne change rien.

# plain_clone_repo_ready RACINE sort en 0 quand repo est prêt à la racine :
# son exécutable du venv et .repo/manifests, que pose un init réussi.
plain_clone_repo_ready() {
    [ -x "${1}/.venv.erplibre/bin/repo" ] && [ -d "${1}/.repo/manifests" ]
}

# plain_clone_extracted RACINE CHEMIN sort en 0 quand repo extrait CHEMIN :
# « repo list -p --all » le nomme, selon les groupes de l'init. Sans --all,
# repo list ne nomme que les projets déjà extraits, et rien juste après un
# premier init. Le shebang de repo est relatif à la racine. Une liste
# illisible vaut « pas extrait ».
plain_clone_extracted() {
    local geres
    geres="$(cd "${1}" && .venv.erplibre/bin/repo list -p --all 2>/dev/null || true)"
    grep -qxF "${2}" <<<"${geres}"
}

# plain_clone_by_repo DIR sort en 0 quand DIR est une extraction de repo :
# .git en lien (repo actuel), répertoire dont objects/ est un lien (ancienne
# disposition de repo), ou fichier qui pointe dans .repo/ (repo init
# --worktree).
plain_clone_by_repo() {
    [ -L "${1}/.git" ] || [ -L "${1}/.git/objects" ] \
        || { [ -f "${1}/.git" ] && grep -q '/\.repo/' "${1}/.git"; }
}

# plain_clone_local_work DIR écrit, sur une ligne, le travail local que
# porte le clone ordinaire DIR, et rien quand il n'en porte pas de visible :
# un .git en fichier (worktree lié ou --separate-git-dir), une modification
# ou un fichier non suivi, un commit absent de ses remotes, une remise, un
# worktree lié. Le mode des fichiers non suivis est fixé, pour qu'un
# status.showUntrackedFiles=no de l'utilisateur ne les cache pas.
# refs/erplibre/installed marque le commit que l'installateur a extrait :
# un main réécrit en amont ne le fait pas passer pour un commit local.
plain_clone_local_work() {
    local modifs locaux liees
    if [ ! -d "${1}/.git" ]; then
        echo "its .git is a file: a linked worktree or a separate git dir"
        return 0
    fi
    modifs="$(git -C "${1}" status --porcelain --untracked-files=normal)"
    if [ -n "${modifs}" ]; then
        echo "changes or untracked files: $(echo "${modifs}" | head -3 | tr '\n' ' ')"
        return 0
    fi
    locaux="$(git -C "${1}" rev-list HEAD --branches --not --remotes --tags \
        --glob='refs/erplibre/*')"
    if [ -n "${locaux}" ]; then
        echo "commits on no remote: $(echo "${locaux}" | wc -l)"
        return 0
    fi
    if [ -n "$(git -C "${1}" stash list)" ]; then
        echo "a stash"
        return 0
    fi
    liees="$(git -C "${1}" worktree list --porcelain | grep -c '^worktree ' || true)"
    if [ "${liees}" -gt 1 ]; then
        echo "linked worktrees: $((liees - 1))"
    fi
}
