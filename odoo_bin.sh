#!/usr/bin/env bash
# This is required to change environment for the running Odoo
source ./.venv.$(< .erplibre-version)/bin/activate

# Le config.conf du DÉPÔT, pas le ~/.odoorc de qui lance. Un « -c »
# explicite l'emporte toujours : Odoo lit opt.config avant ODOO_RC.
source ./script/lib_odoo_rc.sh
odoo_rc_resolve "$(pwd)"

ODOO_PATH="$(pwd)/odoo$(< .odoo-version)"
#export PATH=$ODOO_PATH:$PATH
#echo $PATH
#echo $PYTHONPATH
#export PYTHONPATH="${ODOO_PATH}:${ODOO_PATH}/addons:$PYTHONPATH"
export PYTHONPATH="${ODOO_PATH}:$PYTHONPATH"
#echo $PYTHONPATH

# Odoo 8 et 9 s'appellent encore « openerp » : paquet openerp/, lanceur
# openerp-server. Depuis 10, paquet odoo/ et lanceur odoo-bin. Chaque
# détection ci-dessous lit les sources du paquet de CETTE version.
if [[ -d "${ODOO_PATH}/odoo/openerp" ]]; then
  EL_PKG="${ODOO_PATH}/odoo/openerp"
  EL_LAUNCHER="${ODOO_PATH}/odoo/openerp-server"
else
  EL_PKG="${ODOO_PATH}/odoo/odoo"
  EL_LAUNCHER="${ODOO_PATH}/odoo/odoo-bin"
fi
EL_CONFIG_PY="${EL_PKG}/tools/config.py"
EL_CLI_ADDONS="--addons-path=$(pwd)/script/odoo/cli_addons"

# el_option_connue <option> : la configuration de cette version déclare-t-elle
# l'option ? Odoo l'écrit entre guillemets doubles ou simples selon la version.
el_option_connue() {
  grep -qE "[\"']${1}[\"']" "${EL_CONFIG_PY}" 2> /dev/null
}

# « db » est la commande du fork ERPLibre d'Odoo, que reconnaît son option
# --restore_image. Un Odoo amont n'en a pas (8 à 11) ou en a une d'une autre
# interface (19, 20) : l'appel va alors à erplibre_db, qui prend les mêmes
# options, dans script/odoo/cli_addons. Le lanceur ne découvre la commande
# d'un addon que si --addons-path la précède.
if [[ "${1:-}" == "db" ]] \
  && ! grep -q "restore_image" "${EL_PKG}/cli/db.py" 2> /dev/null; then
  shift
  set -- "${EL_CLI_ADDONS}" erplibre_db "$@"
fi

# « shell » n'existe que depuis Odoo 9 : en 8, erplibre_shell exécute l'entrée
# standard avec « env », comme le shell d'Odoo quand elle n'est pas un terminal.
if [[ "${1:-}" == "shell" && ! -f "${EL_PKG}/cli/shell.py" ]]; then
  shift
  set -- "${EL_CLI_ADDONS}" erplibre_shell "$@"
fi

# Les options « --http-* », « -p » et « --no-http » n'existent que depuis
# Odoo 11 ; Odoo 8 à 10 les nomment « --xmlrpc-* » et « --no-xmlrpc », que 11
# garde en alias cachés. Les scripts écrivent la forme récente, traduite ici
# pour l'Odoo qui ne la connaît pas.
if ! el_option_connue "--no-http"; then
  EL_ARGS=()
  for arg in "$@"; do
    case "${arg}" in
      --no-http) arg="--no-xmlrpc" ;;
      -p) arg="--xmlrpc-port" ;;
      --http-port | --http-port=* | --http-interface | --http-interface=*)
        arg="--xmlrpc-${arg#--http-}"
        ;;
    esac
    EL_ARGS+=("${arg}")
  done
  set -- "${EL_ARGS[@]}"
fi

# « --dev <mode> » prend une valeur depuis Odoo 10. Odoo 9 n'a qu'un drapeau
# « --dev », sans valeur ; Odoo 8 n'a pas l'option du tout. Le mode y passe
# alors par ERPLIBRE_DEV_MODE, que lisent les modules de neutralisation du
# dépôt development pour refuser une installation hors développement.
if ! el_option_connue "--dev" \
  || grep -qE "[\"']--dev[\"'].*store_true" "${EL_CONFIG_PY}" 2> /dev/null; then
  EL_ARGS=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dev | --dev=*)
        if [[ "$1" == --dev=* ]]; then
          EL_DEV="${1#--dev=}"
        elif [[ $# -gt 1 && "$2" != -* ]]; then
          EL_DEV="$2"
          shift
        else
          EL_DEV="all"
        fi
        export ERPLIBRE_DEV_MODE="${EL_DEV}"
        el_option_connue "--dev" && EL_ARGS+=("--dev")
        ;;
      *) EL_ARGS+=("$1") ;;
    esac
    shift
  done
  set -- "${EL_ARGS[@]}"
fi

# « --uninstall » est une option du fork ERPLibre d'Odoo. Pour un Odoo amont,
# l'appel va à erplibre_uninstall, qui prend les mêmes arguments.
if [[ " $* " == *" --uninstall "* || " $* " == *" --uninstall="* ]] \
  && ! el_option_connue "--uninstall"; then
  set -- "${EL_CLI_ADDONS}" erplibre_uninstall "$@"
fi

if [ "$ODOO_MODE_COVERAGE" = "true" ]; then
  coverage run -p "${EL_LAUNCHER}" "$@"
else
  # « python » : celui du venv activé, Python 2 compris, qui n'a pas de python3.
  python "${EL_LAUNCHER}" "$@"
fi
