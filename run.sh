#!/usr/bin/env bash
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

# Search by default local configuration
CONFIG_PATH="./config.conf"
ORIGIN_CONFIG_PATH=CONFIG_PATH
if [ ! -f "${CONFIG_PATH}" ]; then
  CONFIG_PATH="/etc/odoo/odoo.conf"
  if [ ! -f "${CONFIG_PATH}" ]; then
    echo "${Red}Cannot find${Color_Off} ERPLibre configuration ${ORIGIN_CONFIG_PATH}, did you install ERPLibre? > make install"
    exit 1
  fi
fi

# Deux options qui appartiennent à ERPLibre, retirées avant de passer la
# main : Odoo ne les connaît pas et mourrait sur « no such option ».
#   --auto-erplibre    arme le choix de la base à démarrer
#   --no-cli-erplibre  interdit le menu, sans interdire le choix
#   --erplibre-disable-warmup-http  n'envoie pas la requête de réveil
# Sans AUCUN argument, le choix s'arme de lui-même : c'est « make run »,
# quelqu'un devant son terminal. Ce défaut-là reste timide — il exige un
# terminal des deux côtés — parce que systemd lance lui aussi run.sh sans
# argument, avec Restart=always.
EL_ARGS=()
EL_AUTO=0
EL_AUTO_EXPLICITE=0
EL_NO_CLI=0
EL_WARMUP=1
[ $# -eq 0 ] && EL_AUTO=1
while [ $# -gt 0 ]; do
  case "$1" in
    --auto-erplibre)
      EL_AUTO=1
      EL_AUTO_EXPLICITE=1
      ;;
    --no-cli-erplibre) EL_NO_CLI=1 ;;
    --erplibre-disable-warmup-http) EL_WARMUP=0 ;;
    # Rien à réveiller si personne n'écoute. On les laisse passer à Odoo,
    # on se contente de ne pas sonder.
    --no-http|--stop-after-init)
      EL_WARMUP=0
      EL_ARGS+=("$1")
      ;;
    # Tout le reste passe tel quel, y compris les arguments vides et ceux
    # qui portent des espaces : un tableau, jamais une chaîne reconstruite.
    *) EL_ARGS+=("$1") ;;
  esac
  shift
done

EL_DB=()
EL_LIB="./script/database/lib_db_select.sh"
if [ "${EL_AUTO}" = "1" ] && [ -f "${EL_LIB}" ]; then
  # shellcheck source=script/database/lib_db_select.sh
  . "${EL_LIB}"
  EL_DB_NAME="$(el_db_select "${CONFIG_PATH}" "${EL_NO_CLI}" \
    "${EL_AUTO_EXPLICITE}" "${EL_ARGS[@]}")"
  retSelect=$?
  # 130 : on a renoncé au menu. Ne pas démarrer Odoo pour autant, et ne pas
  # rendre 1 non plus — run.sh:26 réserve déjà 1 à « Odoo a échoué ».
  if [ ${retSelect} -eq 130 ]; then
    exit 130
  fi
  if [ -n "${EL_DB_NAME}" ]; then
    EL_DB=(-d "${EL_DB_NAME}")
  fi
fi

# Le réveil, EN PARALLÈLE. Odoo ne charge le registre d'une base qu'à la
# première requête qui la concerne ; sur une base migrée cela prend des
# dizaines de secondes, et c'est la personne qui ouvre la page qui les
# attend. La sonde prend ce temps à sa place, se tait, et meurt avec nous.
EL_WARMUP_PID=""
EL_WARMUP_BIN="./script/odoo/warmup_http.py"
if [ "${EL_WARMUP}" = "1" ] && [ "$ODOO_MODE_TEST" != "true" ] \
   && [ -f "${EL_WARMUP_BIN}" ]; then
  EL_WARMUP_DB=()
  [ -n "${EL_DB_NAME}" ] && EL_WARMUP_DB=(-d "${EL_DB_NAME}")
  # `--` sépare NOS options de celles d'Odoo : sans lui, un « -c » destiné
  # à Odoo serait lu comme le nôtre.
  python3 "${EL_WARMUP_BIN}" -c "${CONFIG_PATH}" "${EL_WARMUP_DB[@]}" \
    -- "${EL_ARGS[@]}" 2>/dev/null &
  EL_WARMUP_PID=$!
  # Elle ne doit pas survivre au serveur qu'elle réveille. Un Ctrl-C sur
  # run.sh doit tout emporter.
  trap '[ -n "${EL_WARMUP_PID}" ] && kill "${EL_WARMUP_PID}" 2>/dev/null' EXIT
fi

if [ "$ODOO_MODE_TEST" = "true" ]; then
  ./odoo_bin.sh -c "${CONFIG_PATH}" --limit-time-real 99999 --limit-time-cpu 99999 --limit-memory-hard=0 --log-level=test --test-enable --no-http --stop-after-init "${EL_DB[@]}" "${EL_ARGS[@]}"
else
  ./odoo_bin.sh -c "${CONFIG_PATH}" --limit-time-real 99999 --limit-time-cpu 99999 --limit-memory-hard=0 "${EL_DB[@]}" "${EL_ARGS[@]}"
fi
# When need more memory RAM for instance by force
#python3 ./odoo/odoo-bin -c ${CONFIG_PATH} --limit-time-real 99999 --limit-time-cpu 99999 --limit-memory-soft=8589934592 --limit-memory-hard=10737418240 $@

retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "${Red}Error${Color_Off} run.sh"
  exit 1
fi
