#!/usr/bin/env bash
Red='\033[0;31m'    # Red
Color_Off='\033[0m' # Text Reset

# This script will remove mail configuration, remove backup configuration, and force admin user to test/test
echo "Update prod to dev on BD '$1'"

# disable_auto_backup vide les sauvegardes d'OCA auto_backup, et n'a de sens
# que là où ce module existe : server-tools n'a pas de branche pour toutes les
# versions d'Odoo. Les trois autres restent exigés — une copie qui ne les a
# pas enverrait des courriels, et l'installation doit alors échouer.
MODULES="user_test,disable_mail_server,disable_payment_provider"
if ./script/addons/check_addons_exist.py -m auto_backup > /dev/null 2>&1; then
  MODULES="${MODULES},disable_auto_backup"
else
  echo "auto_backup absent de cette version : disable_auto_backup est saute."
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
