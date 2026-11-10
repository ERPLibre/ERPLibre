#!/usr/bin/env bash
Red='\033[0;31m'    # Red
Color_Off='\033[0m' # Text Reset

# This script will remove mail configuration, remove backup configuration, and force admin user to test/test
echo "Update prod to dev on BD '$1'"

# disable_auto_backup vide les sauvegardes d'OCA auto_backup, et n'a de sens
# que sur une base où auto_backup est INSTALLÉ, dans une version où ce module
# existe : server-tools n'a pas de branche pour toutes les versions d'Odoo.
# Sur une base sans auto_backup, l'installer tirerait auto_backup avec lui là
# où il en dépend, ou échouerait sur le modèle db.backup absent là où il n'en
# dépend pas. Les trois autres restent exigés — une copie qui ne les a pas
# enverrait des courriels, et l'installation doit alors échouer. psql suit
# PGHOST et PGPORT, comme Odoo : la base est lue sur le serveur qui la porte.
MODULES="user_test,disable_mail_server,disable_payment_provider"
AUTO_BACKUP=$(psql -X -w -d "$1" -tAc "SELECT 1 FROM ir_module_module WHERE name = 'auto_backup' AND state = 'installed'" 2> /dev/null)
if [[ "${AUTO_BACKUP}" != "1" ]]; then
  echo "auto_backup n'est pas installe sur '$1' : disable_auto_backup est saute."
elif ! ./script/addons/check_addons_exist.py -m auto_backup > /dev/null 2>&1; then
  echo "auto_backup absent de cette version : disable_auto_backup est saute."
else
  MODULES="${MODULES},disable_auto_backup"
fi

./script/addons/install_addons_dev.sh "$1" "${MODULES}"

retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} install_addons.sh into update_prod_to_dev.sh"
  exit 1
fi

echo "Update trace of prod to dev on BD '$1'"

./script/addons/uninstall_addons.sh "$1" "${MODULES}"

retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} uninstall_addons.sh into update_prod_to_dev.sh"
  exit 1
fi
