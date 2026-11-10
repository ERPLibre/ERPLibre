#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Prépare script/gnome-extension/erplibre_home/ pour repo sync. Les scripts
# update_manifest_*.sh le lancent après « repo init », après
# streamdeck_games_to_repo.sh, et juste avant « repo sync » :
#
#   ./script/manifest/erplibre_home_extension_to_repo.sh [racine]
#
# L'extension GNOME est un dépôt à part qu'un checkout reçoit de deux
# façons : repo sync, par manifest/git_manifest_erplibre_home_gnome_extension.xml,
# ou un « git clone » ordinaire d'install_erplibre_home.sh. La session GNOME
# charge l'extension par un lien vers ce répertoire : il ne doit jamais
# manquer ni se vider, même le temps d'une synchronisation. Deux
# comportements de repo sync le menacent :
#
# - il refuse un clone ordinaire (« .git: unsupported checkout state »).
#   Quand repo va extraire l'extension, seul le .git du clone passe donc
#   dans erplibre_home.plain-clone-git-<date>/ à côté ; les fichiers
#   restent, et repo sync, qui adopte un répertoire sans .git, extrait main
#   par-dessus. Un clone qui porte du travail local visible (modification,
#   fichier non suivi, commit absent de ses remotes, remise, worktree lié)
#   reste en place, et le script sort en 1 en le nommant ;
# - il supprime le répertoire d'un projet qu'il gère quand l'init ne
#   l'extrait plus (groupes, manifeste) : l'extension de la session. Le
#   script sort alors en 1, avant repo sync, en nommant le groupe
#   erplibre_home.
#
# Rien n'est supprimé par ce script ; ce qu'il met de côté se retire à la
# main une fois inutile. Les lectures sont celles de plain_clone_lib.sh.
# Sans repo prêt à la racine, il n'y a rien à préparer.
#
# Codes de sortie : 0 rien à faire, ou .git mis de côté ; 1 clone retenu,
# ou extension que repo sync supprimerait.
set -euo pipefail

RACINE="${1:-.}"
# shellcheck source=script/manifest/plain_clone_lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/plain_clone_lib.sh"
EXT="script/gnome-extension/erplibre_home"
DIR="${RACINE}/${EXT}"
DATE="$(date +%Y%m%d-%H%M%S)"

log() { echo "[ERPLibre] ${EXT}/: $*"; }

retenu() {
    log "kept, repo sync cannot take it over: $*" >&2
    echo "[ERPLibre] push that work or move it out of ${EXT}/, then run" \
        "the update again: its .git will be moved aside, its files kept" >&2
    exit 1
}

[ -e "${DIR}/.git" ] || [ -L "${DIR}/.git" ] || exit 0
plain_clone_repo_ready "${RACINE}" || exit 0

extrait=0
if plain_clone_extracted "${RACINE}" "${EXT}"; then
    extrait=1
fi

if plain_clone_by_repo "${DIR}"; then
    [ "${extrait}" = 1 ] && exit 0
    log "repo sync would remove it: this init does not extract it" >&2
    echo "[ERPLibre] add the erplibre_home group to repo init (-g ...," \
        "erplibre_home), then run the update again" >&2
    exit 1
fi

[ "${extrait}" = 1 ] || exit 0
travail="$(plain_clone_local_work "${DIR}")"
[ -z "${travail}" ] || retenu "${travail}"

mv "${DIR}/.git" "${DIR}.plain-clone-git-${DATE}"
log "git clone's .git moved to ${EXT}.plain-clone-git-${DATE} for repo sync, files kept"
