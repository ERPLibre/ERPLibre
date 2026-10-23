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

if [ "$ODOO_MODE_COVERAGE" = "true" ]; then
  coverage run -p ./odoo$(< .odoo-version)/odoo/odoo-bin "$@"
else
  python3 ./odoo$(< .odoo-version)/odoo/odoo-bin "$@"
fi
