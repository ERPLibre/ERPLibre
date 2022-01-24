#!/usr/bin/env bash
if (($# < 1)); then
  echo "ERROR, need 1 arguments: log file path"
  exit 1
fi

Color_Off='\033[0m'
Red='\033[0;31m'
Blue='\033[0;34m'
Yellow='\033[0;33m'
LOG_FILE="${1}"

echo "== RESULT from ${LOG_FILE} =="
WARNING_MESSAGE=$(grep -i warning "${LOG_FILE}")
WARNING_MESSAGE=$(echo "${WARNING_MESSAGE}"|grep -v "have the same label:")
WARNING_MESSAGE=$(echo "${WARNING_MESSAGE}"|grep -v "odoo.addons.code_generator.extractor_module_file: Ignore next error about ALTER TABLE DROP CONSTRAINT.")
# Remove empty line
if [[ -z "${WARNING_MESSAGE// }" ]]; then
  COUNT_WARNING=0
else
  COUNT_WARNING=$(echo "${WARNING_MESSAGE}"|wc -l)
fi

ERROR_MESSAGE=$(grep -i error "${LOG_FILE}")
ERROR_MESSAGE=$(echo "${ERROR_MESSAGE}"|grep -v "fetchmail_notify_error_to_sender")
ERROR_MESSAGE=$(echo "${ERROR_MESSAGE}"|grep -v "odoo.sql_db: bad query: ALTER TABLE \"db_backup\" DROP CONSTRAINT \"db_backup_db_backup_name_unique\"")
ERROR_MESSAGE=$(echo "${ERROR_MESSAGE}"|grep -v "ERROR: constraint \"db_backup_db_backup_name_unique\" of relation \"db_backup\" does not exist")
ERROR_MESSAGE=$(echo "${ERROR_MESSAGE}"|grep -v "odoo.sql_db: bad query: ALTER TABLE \"db_backup\" DROP CONSTRAINT \"db_backup_db_backup_days_to_keep_positive\"")
ERROR_MESSAGE=$(echo "${ERROR_MESSAGE}"|grep -v "ERROR: constraint \"db_backup_db_backup_days_to_keep_positive\" of relation \"db_backup\" does not exist")
ERROR_MESSAGE=$(echo "${ERROR_MESSAGE}"|grep -v "odoo.addons.code_generator.extractor_module_file: Ignore next error about ALTER TABLE DROP CONSTRAINT.")
# Remove empty line
if [[ -z "${ERROR_MESSAGE// }" ]]; then
  COUNT_ERROR=0
else
  COUNT_ERROR=$(echo "${ERROR_MESSAGE}"|wc -l)
fi

echo_count_warnings () {
    if (("${COUNT_WARNING}" > 1)); then
    echo -e "${Yellow}${COUNT_WARNING} WARNINGS${Color_Off}"
  else
    echo -e "${Yellow}${COUNT_WARNING} WARNING${Color_Off}"
  fi
}
echo_count_errors () {
    if (("${COUNT_ERROR}" > 1)); then
    echo -e "${Red}${COUNT_ERROR} ERRORS${Color_Off}"
  else
    echo -e "${Red}${COUNT_ERROR} ERROR${Color_Off}"
  fi
}

echo -e "${Blue}Summary of check result${Color_Off}"
if (("${COUNT_WARNING}" > 0)); then
  echo_count_warnings
fi

if (("${COUNT_ERROR}" > 0)); then
  echo_count_errors
fi

echo -e "${Blue}Log result${Color_Off}"
if (("${COUNT_WARNING}" > 0)); then
  if (("${COUNT_ERROR}" > 0)); then
    echo_count_warnings
  fi
  echo -e "${WARNING_MESSAGE}"
fi

if (("${COUNT_ERROR}" > 0)); then
  if (("${COUNT_WARNING}" > 0)); then
    echo_count_errors
  fi
  echo -e "${ERROR_MESSAGE}"
fi

echo -e "${Blue}End of check result${Color_Off}"
