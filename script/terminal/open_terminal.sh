#!/usr/bin/env bash

CMD_TO_EXEC="$1"
PATHS_RAW="$2"
#paths="$2"
echo "Script start open_terminal.sh"
echo "$PATHS_RAW"
IFS=$'\n' read -r -d '' -a paths <<< "$PATHS_RAW"
echo "$path"
SOURCE_CMD="source ./.venv.erplibre/bin/activate"
FIRST_ITERATION=true
SECOND_ITERATION=true

which gnome-terminal
GNOME_TERMINAL_CMD=$(which gnome-terminal)

HAS_GNOME_TERMINAL=false
HAS_TELL_TERMINAL=false
#if command -v gnome-terminal &>/dev/null; then
#  HAS_GNOME_TERMINAL=true
#  echo "Detect gnome-terminal"
##elif command -v tell &>/dev/null; then
#elif [[ "${OSTYPE}" == "darwin"* ]] && command -v osascript &>/dev/null; then
#if [[ "${OSTYPE}" == "darwin"* ]] && command -v osascript &>/dev/null; then
# TODO validate osascript is implemented
if [[ "${OSTYPE}" == "darwin"* ]] then
  echo "Detect osascript Darwin"
  HAS_TELL_TERMINAL=true
else
  echo "Detect cli"
fi

if [[ -z "$paths" ]]; then
  working_path=$(readlink -f .)
  paths="${working_path}/"
fi

#if [[ "${OSTYPE}" == "linux-gnu" ]]; then
if [ "$HAS_GNOME_TERMINAL" = true ]; then
  CMD_BEFORE="cd "
  CMD_AFTER_FIRST=";gnome-terminal --tab -- /bin/bash -c '${SOURCE_CMD};${CMD_TO_EXEC};bash';"
  CMD_AFTER=";gnome-terminal --tab -- /bin/bash -c '${CMD_TO_EXEC};bash';"
  LONGCMD=""
  for PATH in "${paths[@]}"; do
    if [[ ! -e "${PATH}" ]]; then
      continue
    fi
    if $FIRST_ITERATION; then
      LONGCMD+="${CMD_BEFORE}${PATH}${CMD_AFTER_FIRST}"
      FIRST_ITERATION=false
    else
      LONGCMD+="${CMD_BEFORE}${PATH}${CMD_AFTER}"
    fi
  done
  echo "${LONGCMD}"
  echo "${GNOME_TERMINAL_CMD}"
#  $GNOME_TERMINAL_CMD --window -- /bin/bash -c "ls"
  $GNOME_TERMINAL_CMD --window -- /bin/bash -c "${LONGCMD}"
elif [ "$HAS_TELL_TERMINAL" = true ]; then
  paths=("${paths[@]:1}")

  # Initialisation de la commande osascript
  osascript_command="osascript -e 'tell application \"Terminal\"'"

  # Boucle pour ajouter des commandes pour ouvrir de nouveaux onglets et exécuter les scripts batch
  for PATH in "${paths[@]}"; do
    if [[ ! -e "${PATH}" ]]; then
      continue
    fi
    if $FIRST_ITERATION; then
      osascript_command+=" -e 'tell application \"System Events\" to keystroke \"PATH\" using {command down}' -e 'delay 0.1' -e 'do script \"cd ${PATH}; ${SOURCE_CMD}; ${CMD_TO_EXEC}\" in front window'"
      FIRST_ITERATION=false
    elif $SECOND_ITERATION; then
      osascript_command+=" -e 'tell application \"System Events\" to keystroke \"PATH\" using {command down}' -e 'delay 0.1' -e 'do script \"cd ${PATH}; ${SOURCE_CMD}; ${CMD_TO_EXEC}\" in front window'"
      SECOND_ITERATION=false
    else
      osascript_command+=" -e 'tell application \"System Events\" to keystroke \"PATH\" using {command down}' -e 'delay 0.1' -e 'do script \"cd ${PATH}; ${SOURCE_CMD}; ${CMD_TO_EXEC}\" in front window'"
    fi
  done
  osascript_command+=" -e 'end tell'"

  # Exécution de la commande osascript
  echo "${osascript_command}"
  eval "$osascript_command"
else
#  echo "CLI"
#  for PATH in "${paths[@]}"; do
#    if [[ ! -e "${PATH}" ]]; then
#      continue
#    fi
#    cd ${PATH}
#    echo "${CMD_TO_EXEC}"
#    eval ${CMD_TO_EXEC}
#  done
  echo "Cannot find gnome-terminal (GNOME) or osasscript (OSX)"
  exit 1
fi
