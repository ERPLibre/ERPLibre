#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Prépare script/stream_deck/games/ pour repo sync. Les scripts
# update_manifest_*.sh le lancent après « repo init » et juste avant
# « repo sync » :
#
#   ./script/manifest/streamdeck_games_to_repo.sh [racine]
#
# Les jeux sont un dépôt à part qu'un checkout reçoit de deux façons : repo
# sync, par manifest/git_manifest_streamdeck_game.xml, ou un « git clone »
# ordinaire d'install_erplibre_home.sh --stream-deck. Deux comportements de
# repo sync menacent alors games/ :
#
# - il refuse un clone ordinaire (« .git: unsupported checkout state »),
#   mais adopte un répertoire qui ne garde que des fichiers non suivis.
#   Quand repo va extraire les jeux, le clone passe donc, entier, dans
#   games.plain-clone-<date>/ à côté, et games/ ne garde qu'une copie de
#   save/. Un clone qui porte du travail local visible (modification,
#   fichier non suivi, commit absent de ses remotes, remise, worktree lié)
#   reste en place, et le script sort en 1 en le nommant ;
# - il supprime le répertoire d'un projet qu'il gère quand l'init ne
#   l'extrait plus (groupes, manifeste), save/ compris, que les jeux
#   ignorent. save/ est alors copié dans games.save-<date>/ avant.
#
# Rien n'est supprimé par ce script ; ce qu'il met de côté se retire à la
# main une fois inutile. repo décide seul des projets qu'il extrait :
# « repo list -p --all » le dit, selon les groupes de l'init. Sans --all,
# repo list ne nomme que les projets déjà extraits, et rien juste après un
# premier init. Sans repo prêt à la racine, il n'y a rien à préparer.
#
# Codes de sortie : 0 rien à faire, clone ou sauvegardes mis de côté ;
# 1 clone retenu.
set -euo pipefail

RACINE="${1:-.}"
JEUX="script/stream_deck/games"
DIR="${RACINE}/${JEUX}"
DATE="$(date +%Y%m%d-%H%M%S)"

log() { echo "[ERPLibre] ${JEUX}/: $*"; }

retenu() {
    log "kept, repo sync cannot take it over: $*" >&2
    echo "[ERPLibre] push that work or move it out of ${JEUX}/, then run" \
        "the update again: the clone will be moved aside, save/ kept" >&2
    exit 1
}

[ -e "${DIR}/.git" ] || [ -L "${DIR}/.git" ] || exit 0
[ -x "${RACINE}/.venv.erplibre/bin/repo" ] \
    && [ -d "${RACINE}/.repo/manifests" ] || exit 0

# Le shebang de repo est relatif à la racine. Une liste illisible vaut
# « pas extrait » : le clone ordinaire reste, et pour un games/ de repo,
# save/ n'est que copié.
geres="$(cd "${RACINE}" && .venv.erplibre/bin/repo list -p --all 2>/dev/null || true)"
extrait=0
if grep -qxF "${JEUX}" <<<"${geres}"; then
    extrait=1
fi

# Extrait par repo : .git en lien (repo actuel), répertoire dont objects/
# est un lien (ancienne disposition de repo), ou fichier qui pointe dans
# .repo/ (repo init --worktree).
if [ -L "${DIR}/.git" ] || [ -L "${DIR}/.git/objects" ] \
    || { [ -f "${DIR}/.git" ] && grep -q '/\.repo/' "${DIR}/.git"; }; then
    [ "${extrait}" = 1 ] && exit 0
    if [ -n "$(find "${DIR}/save" -mindepth 1 ! -name .gitkeep -print -quit 2>/dev/null)" ]; then
        cp -a "${DIR}/save" "${DIR}.save-${DATE}"
        log "repo sync will remove it (out of this init); save/ copied to ${JEUX}.save-${DATE}"
    fi
    exit 0
fi

[ "${extrait}" = 1 ] || exit 0
[ -d "${DIR}/.git" ] \
    || retenu "its .git is a file: a linked worktree or a separate git dir"

# Ces lectures ne servent qu'à prévenir : le clone déplacé garde de toute
# façon ce qu'elles manqueraient. Le mode des fichiers non suivis est fixé,
# pour qu'un status.showUntrackedFiles=no de l'utilisateur ne les cache pas.
modifs="$(git -C "${DIR}" status --porcelain --untracked-files=normal)"
[ -z "${modifs}" ] || retenu "changes or untracked files: $(echo "${modifs}" | head -3 | tr '\n' ' ')"
# refs/erplibre/installed marque le commit que l'installateur a extrait :
# un main réécrit en amont ne le fait pas passer pour un commit local.
locaux="$(git -C "${DIR}" rev-list HEAD --branches --not --remotes --tags \
    --glob='refs/erplibre/*')"
[ -z "${locaux}" ] || retenu "commits on no remote: $(echo "${locaux}" | wc -l)"
[ -z "$(git -C "${DIR}" stash list)" ] || retenu "a stash"
liees="$(git -C "${DIR}" worktree list --porcelain | grep -c '^worktree ' || true)"
[ "${liees}" -le 1 ] || retenu "linked worktrees: $((liees - 1))"

mv "${DIR}" "${DIR}.plain-clone-${DATE}"
mkdir "${DIR}"
if [ -d "${DIR}.plain-clone-${DATE}/save" ]; then
    cp -a "${DIR}.plain-clone-${DATE}/save" "${DIR}/save"
fi
log "git clone moved to ${JEUX}.plain-clone-${DATE} for repo sync, save/ copied back"
