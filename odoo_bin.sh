#!/usr/bin/env bash
# This is required to change environment for the running Odoo
source ./.venv.$(< .erplibre-version)/bin/activate

# Le config.conf du DÉPÔT, pas le ~/.odoorc de qui lance. Un « -c »
# explicite l'emporte toujours : Odoo lit opt.config avant ODOO_RC.
source ./script/lib_odoo_rc.sh
odoo_rc_resolve "$(pwd)"

# Vrai quand le cœur odoo${VERSION}/odoo porte encore l'ancienne commande
# « db » à drapeaux, et avec elle les options serveur --uninstall et
# --install-theme : son odoo/cli/db.py n'a pas le _check_target du « db »
# d'OCB. C'est le cas de 12 à 15, et d'un fork 16 ou 17 resté sur ses
# anciens commits (doc/improve_odoo.md). La décision suit le cœur et non le
# module : un module présent à côté d'un ancien cœur ne remplace rien
# (son cli/__init__.py fait le même test), et la traduction reste juste.
odoo_cli_is_legacy() {
  ! grep -qs "def _check_target" "odoo${1}/odoo/odoo/cli/db.py"
}

# Vrai quand le dépôt ERPLibre_erplibre_addons de VERSION porte le module.
odoo_cli_has_module() {
  [ -f "odoo${1}/addons/ERPLibre_erplibre_addons/erplibre_odoo_cli_base/__manifest__.py" ]
}

# Les appelants écrivent la syntaxe d'Odoo 18 (« db list », « module
# uninstall », « theme apply »). Sur un ancien cœur, le traducteur la
# convertit ; sur un cœur d'OCB, le module la porte, et sans lui ces
# commandes n'existent pas : sortie 2, avant qu'Odoo ne refuse la syntaxe
# moins clairement. ERPLIBRE_ODOO_CLI_LEGACY marque les appels du
# traducteur, qui vont tout droit à l'ancienne commande.
case "${1:-}" in
  db | module | theme)
    if [ -z "${ERPLIBRE_ODOO_CLI_LEGACY:-}" ]; then
      ODOO_CLI_VERSION="$(< .odoo-version)"
      if odoo_cli_is_legacy "${ODOO_CLI_VERSION}"; then
        exec python3 ./script/database/odoo_db_legacy.py "$@"
      elif ! odoo_cli_has_module "${ODOO_CLI_VERSION}"; then
        echo "odoo_bin.sh ${1}: erplibre_odoo_cli_base missing for" \
          "odoo${ODOO_CLI_VERSION}: the Odoo core has OCB's db command," \
          "and the module odoo${ODOO_CLI_VERSION}/addons/ERPLibre_erplibre_addons/erplibre_odoo_cli_base" \
          "brings db, module and theme (doc/improve_odoo.md)." >&2
        exit 2
      fi
    fi
    ;;
esac

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
