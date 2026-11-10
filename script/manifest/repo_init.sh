# Fragment à sourcer depuis la racine d'ERPLibre :
#
#     . ./script/manifest/repo_init.sh
#     repo_init -u <url> -b "${MANIFEST_REV}" -m <manifeste> [options]
#
# repo_init lance « .venv.erplibre/bin/repo init » avec ses arguments, sans
# qu'il pose de question. Sur un terminal, repo init en pose deux qui
# arrêtent l'installation :
#
# - « Enable color display in this user account (y/N)? », tant que la config
#   git de l'utilisateur ne porte ni color.ui, ni color.diff, ni
#   color.status. repo_color_default écrit d'avance ce que la réponse « y »
#   écrirait, color.ui = auto, et laisse intact un choix déjà présent.
# - « Your Name », « Your Email », puis « is this correct [y/N]? », tant que
#   user.name ou user.email ne se trouve ni dans le projet de manifeste
#   (.repo/manifests.git/config) ni dans la config git de l'utilisateur ;
#   chaque clé peut venir de l'un ou de l'autre. Aucune réponse ne s'écrit
#   d'avance : une identité ne s'invente pas. repo_init lance alors repo
#   init avec l'entrée sur /dev/null ; repo ne pose ses questions que si
#   l'entrée et la sortie sont des terminaux, et passe outre. L'identité ne
#   sert qu'à « repo upload », qu'ERPLibre n'emploie pas. Le menu
#   Installation de TODO propose de la saisir avant de lancer l'installation,
#   par repo_identity_set. --config-name parmi les arguments demande
#   expressément la question : l'entrée reste alors celle de l'appelant.
#
# Le fichier lu est celui que lit repo, pas celui qu'écrirait
# « git config --global » : repo prend $XDG_CONFIG_HOME/git/config (défaut
# ~/.config/git/config) s'il existe, sinon ~/.gitconfig. Quand les deux
# existent, git écrit dans ~/.gitconfig et repo poserait encore la question.
# Un XDG_CONFIG_HOME défini mais vide donne à repo le chemin relatif
# git/config, là où git prendrait le défaut. La lecture suit les inclusions,
# comme celle de repo.

# Rend sur stdout le chemin de la config git utilisateur que lit repo.
repo_user_config() {
  local xdg="${XDG_CONFIG_HOME-${HOME}/.config}"
  local config="${xdg:+${xdg}/}git/config"
  [ -e "${config}" ] || config="${HOME}/.gitconfig"
  printf '%s\n' "${config}"
}

# Rend 0 si le fichier $1 porte la clé $2, inclusions comprises.
_repo_config_has() {
  [ -e "$1" ] && git config --file "$1" --includes --get "$2" >/dev/null 2>&1
}

repo_color_default() {
  local config cle
  config="$(repo_user_config)"
  for cle in color.ui color.diff color.status; do
    _repo_config_has "${config}" "${cle}" && return 0
  done
  git config --file "${config}" color.ui auto
}

# Rend 0 quand repo init ne demandera pas d'identité : user.name et
# user.email se trouvent chacun dans le projet de manifeste ou, à défaut,
# dans la config utilisateur. Rend 1 sinon.
repo_identity_ready() {
  local config cle
  config="$(repo_user_config)"
  for cle in user.name user.email; do
    _repo_config_has .repo/manifests.git/config "${cle}" \
      || _repo_config_has "${config}" "${cle}" \
      || return 1
  done
}

# Écrit user.name=$1 et user.email=$2 dans la config utilisateur que lit
# repo. Rend 1, sans rien écrire, si l'un des deux est vide.
repo_identity_set() {
  local config
  [ -n "$1" ] && [ -n "$2" ] || return 1
  config="$(repo_user_config)"
  git config --file "${config}" user.name "$1" \
    && git config --file "${config}" user.email "$2"
}

repo_init() {
  local arg
  repo_color_default
  for arg in "$@"; do
    if [ "${arg}" = "--config-name" ]; then
      .venv.erplibre/bin/repo init "$@"
      return
    fi
  done
  if repo_identity_ready; then
    .venv.erplibre/bin/repo init "$@"
  else
    echo "repo init : aucune identité git (user.name, user.email), repo ne la demande pas."
    .venv.erplibre/bin/repo init "$@" </dev/null
  fi
}
