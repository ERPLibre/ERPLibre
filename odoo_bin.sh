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

# « db » est la commande du fork ERPLibre d'Odoo, que reconnaît son option
# --restore_image. Un Odoo amont n'en a pas (10, 11) ou en a une d'une autre
# interface (19, 20) : l'appel va alors à erplibre_db, qui prend les mêmes
# options, dans script/odoo/cli_addons. odoo-bin ne découvre la commande d'un
# addon que si --addons-path la précède.
if [[ "${1:-}" == "db" ]] \
  && ! grep -q "restore_image" "${ODOO_PATH}/odoo/odoo/cli/db.py" 2> /dev/null; then
  shift
  set -- "--addons-path=$(pwd)/script/odoo/cli_addons" erplibre_db "$@"
fi

# Les options « --http-* », « -p » et « --no-http » n'existent que depuis
# Odoo 11 ; Odoo 10 les nomme « --xmlrpc-* » et « --no-xmlrpc », que 11 garde
# en alias cachés. Les scripts écrivent la forme récente, traduite ici pour
# l'Odoo qui ne la connaît pas.
if ! grep -q '"--no-http"' "${ODOO_PATH}/odoo/odoo/tools/config.py" 2> /dev/null; then
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

# « --uninstall » est une option du fork ERPLibre d'Odoo. Pour un Odoo amont,
# l'appel va à erplibre_uninstall, qui prend les mêmes arguments.
if [[ " $* " == *" --uninstall "* || " $* " == *" --uninstall="* ]] \
  && ! grep -q '"--uninstall"' "${ODOO_PATH}/odoo/odoo/tools/config.py" 2> /dev/null; then
  set -- "--addons-path=$(pwd)/script/odoo/cli_addons" erplibre_uninstall "$@"
fi

if [ "$ODOO_MODE_COVERAGE" = "true" ]; then
  coverage run -p ./odoo$(< .odoo-version)/odoo/odoo-bin "$@"
else
  # « python » : celui du venv activé, Python 2 compris, qui n'a pas de python3.
  python ./odoo$(< .odoo-version)/odoo/odoo-bin "$@"
fi
