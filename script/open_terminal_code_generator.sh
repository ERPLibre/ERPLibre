#!/usr/bin/env bash
# Open a new gnome-terminal with different path on new tab
working_path=$(readlink -f .)
paths=(
  "${working_path}/"
  "${working_path}/"
  "${working_path}/addons/ERPLibre_erplibre_addons"
  "${working_path}/addons/TechnoLibre_odoo-code-generator"
  "${working_path}/addons/TechnoLibre_odoo-code-generator-template"
#  "${working_path}/addons/OCA_server-tools"

)

first_iteration=true
second_iteration=true
if [[ "${OSTYPE}" == "linux-gnu" ]]; then
  cmd_before="cd "
  cmd_after_first=";gnome-terminal --tab -- bash -c 'source ./.venv/bin/activate;git status;bash';"
  cmd_after=";gnome-terminal --tab -- bash -c 'git status;bash';"
  LONGCMD=""
  for t in "${paths[@]}"; do
    if [[ ! -e "${t}" ]]; then
      continue
    fi
    if $first_iteration; then
      LONGCMD+="${cmd_before}${t}${cmd_after_first}"
      first_iteration=false
    elif $second_iteration; then
      LONGCMD+="${cmd_before}${t}${cmd_after_first}"
      second_iteration=false
    else
      LONGCMD+="${cmd_before}${t}${cmd_after}"
    fi
  done
  gnome-terminal --window -- bash -c "${LONGCMD}"
elif [[ "${OSTYPE}" == "darwin"* ]]; then
  paths=("${paths[@]:1}")

  # Initialisation de la commande osascript
  osascript_command="osascript -e 'tell application \"Terminal\"'"

  # Boucle pour ajouter des commandes pour ouvrir de nouveaux onglets et exécuter les scripts batch
  for t in "${paths[@]}"; do
    if $first_iteration; then
      osascript_command+=" -e 'tell application \"System Events\" to keystroke \"t\" using {command down}' -e 'delay 0.1' -e 'do script \"cd ${t}; source ./.venv/bin/activate; git status\" in front window'"
      first_iteration=false
    elif $second_iteration; then
      osascript_command+=" -e 'tell application \"System Events\" to keystroke \"t\" using {command down}' -e 'delay 0.1' -e 'do script \"cd ${t}; source ./.venv/bin/activate; git status\" in front window'"
      second_iteration=false
    else
      osascript_command+=" -e 'tell application \"System Events\" to keystroke \"t\" using {command down}' -e 'delay 0.1' -e 'do script \"cd ${t}; git status\" in front window'"
    fi
  done
  osascript_command+=" -e 'end tell'"

  # Exécution de la commande osascript
  eval "$osascript_command"
fi
