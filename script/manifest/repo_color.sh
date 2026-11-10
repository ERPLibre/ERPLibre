# Fragment à sourcer depuis la racine d'ERPLibre, avant « repo init » :
#
#     . ./script/manifest/repo_color.sh
#     repo_color_default
#
# Sur un terminal, « repo init » demande « Enable color display in this user
# account (y/N)? » tant que la config git de l'utilisateur ne porte ni
# color.ui, ni color.diff, ni color.status ; l'installation s'arrête sur
# cette question. repo_color_default écrit d'avance ce que la réponse « y »
# écrirait, color.ui = auto, et laisse intact un choix déjà présent.
#
# Le fichier visé est celui que lit repo, pas celui qu'écrirait
# « git config --global » : repo prend $XDG_CONFIG_HOME/git/config (défaut
# ~/.config/git/config) s'il existe, sinon ~/.gitconfig. Quand les deux
# existent, git écrit dans ~/.gitconfig et repo poserait encore la question.
# La lecture suit les inclusions, comme celle de repo.
repo_color_default() {
  local config="${XDG_CONFIG_HOME:-${HOME}/.config}/git/config"
  [ -e "${config}" ] || config="${HOME}/.gitconfig"
  local cle
  for cle in color.ui color.diff color.status; do
    if git config --file "${config}" --includes --get "${cle}" >/dev/null 2>&1; then
      return 0
    fi
  done
  git config --file "${config}" color.ui auto
}
