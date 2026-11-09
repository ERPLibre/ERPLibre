#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Copie un fichier de l'hôte dans le conteneur ERPLibre du projet docker
# compose du répertoire courant :
#   docker_copy_file.sh <fichier_source> [répertoire_destination]
# Le répertoire de destination est absolu ; DEST_DIR ci-dessous en donne le
# défaut, /home/odoo, le répertoire du compte qui lance Odoo. Les
# répertoires manquants sont créés.
#
# Le fichier passe par l'entrée standard de docker exec, jamais par
# docker cp : avec Docker sans root, docker cp échoue sur « remount-ro ...
# operation not permitted » dès que le conteneur a un montage lié en lecture
# seule dont la source est sur un système de fichiers monté nosuid, nodev ou
# noexec.
#
# Le compose retire toutes les capacités à root, DAC_OVERRIDE compris : root
# n'entre pas dans un répertoire de mode 700 qu'un autre compte possède, comme
# /home/odoo. Le script cherche donc d'abord, dans le chemin canonique de la
# destination, le plus proche ancêtre qui existe, sous un compte qui peut le
# parcourir : le propriétaire de /ERPLibre d'abord, puis le propriétaire du
# répertoire qui l'arrête, au plus trois comptes. L'écrivain est le
# propriétaire de cet ancêtre. Root n'écrit que si tout le chemin existant lui
# appartient, qu'aucun de ses répertoires n'est inscriptible par le groupe ou
# les autres sans le bit collant (la règle de chemin_sur dans
# docker/entrypoint_pip_extra.sh, /tmp en plus), et que l'ancêtre n'est
# inscriptible ni par son groupe ni par les autres ; dans un répertoire ouvert
# à tous comme /tmp, c'est le propriétaire de /ERPLibre, le compte d'Odoo, qui
# écrit. Un lien symbolique posé par un autre compte ne mène donc jamais root
# à écrire hors de ce qui lui appartient, et aucun autre compte ne peut
# remplacer un composant entre le parcours et l'écriture.
#
# Un parcours qui tourne sous un autre compte que root peut être falsifié par
# ce compte, qui lit et écrit la mémoire de ses propres processus. Root
# n'écrit donc que sur la foi d'un parcours fait sous root : quand l'écrivain
# retenu est root, le parcours se refait sous root, et root n'écrit que s'il
# rend le même chemin canonique et vérifie de nouveau la règle ci-dessus ;
# sinon, le propriétaire de /ERPLibre écrit.
#
# L'écrivain crée les répertoires manquants et le fichier sous umask 022,
# soit 755 et 644 : docker exec tourne sous umask 0000, qui les laisserait
# inscriptibles par tous les comptes du conteneur. Un fichier qui existe déjà
# garde son mode.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <source_file> [destination_directory, default /home/odoo]"
  exit 1
fi

SRC_FILE="$1"
DEST_DIR="${2:-/home/odoo}"

if [[ ! -f "$SRC_FILE" ]]; then
  echo "Error: Source file '$SRC_FILE' does not exist."
  exit 1
fi
if [[ "${DEST_DIR}" != /* ]]; then
  echo "Error: the destination directory '${DEST_DIR}' must be absolute."
  exit 1
fi

SRC_BASENAME="$(basename "$SRC_FILE")"

source "$(dirname "$0")/lib_conteneur.sh"
CONTAINER=$(conteneur_erplibre)
CODE_OWNER=$(proprietaire_code "${CONTAINER}")

echo "Detected container: ${CONTAINER}"

# PARCOURS reçoit la destination en $1 et écrit un champ par ligne :
#   ok, uid, mode octal, 1 si tout le chemin existant est sûr pour root
#      sinon 0, ancêtre, chemin canonique ;
#   blocked, uid du répertoire, répertoire qu'on ne peut parcourir ;
#   notdir, chemin existant qui n'est pas un répertoire.
# Le parcours descend depuis « / » : un composant n'est déclaré absent
# qu'après avoir vérifié qu'on peut chercher dans son parent, sans quoi
# « absent » et « interdit » se confondraient. realpath -m résout les liens
# des composants existants ; un lien rencontré ensuite signale un chemin
# changé pendant le parcours, et se refuse comme un non-répertoire.
# « Tout le chemin sûr pour root » se juge sur les deux chemins : chaque
# préfixe existant de la destination telle qu'écrite, lien compris (stat ne
# le suit pas), et chaque composant du chemin canonique. juger met tout_root
# à 0 pour une entrée qui n'est pas à root, ou pour un répertoire inscriptible
# par le groupe ou les autres sans bit collant ; le mode d'un lien, toujours
# 777, ne compte pas. Un lien que odoo pose vers /etc dans /tmp ou /ERPLibre
# fait donc écrire odoo, que /etc refuse.
# shellcheck disable=SC2016
PARCOURS='
tout_root=1
juger() {
  [ "$(stat -c %u -- "$1")" = 0 ] || { tout_root=0; return 0; }
  [ -L "$1" ] && return 0
  m=$(stat -c %a -- "$1")
  if [ $((0$m & 022)) -ne 0 ] && [ $((0$m & 01000)) -eq 0 ]; then
    tout_root=0
  fi
  return 0
}
q=$1
while :; do
  if [ -e "$q" ] || [ -L "$q" ]; then
    juger "$q"
  fi
  [ "$q" = / ] && break
  q=$(dirname -- "$q")
done
canon=$(realpath -m -- "$1") || exit 3
p=/
reste=${canon#/}
while [ -n "$reste" ]; do
  c=${reste%%/*}
  reste=${reste#"$c"}
  reste=${reste#/}
  if [ ! -x "$p" ]; then
    printf "blocked\n%s\n%s\n" "$(stat -c %u "$p")" "$p"
    exit 0
  fi
  n=${p%/}/$c
  [ -e "$n" ] || [ -L "$n" ] || break
  if [ -L "$n" ] || [ ! -d "$n" ]; then
    printf "notdir\n\n%s\n" "$n"
    exit 0
  fi
  p=$n
  juger "$p"
done
printf "ok\n%s\n%s\n%s\n%s\n%s\n" "$(stat -c %u "$p")" "$(stat -c %a "$p")" \
  "$tout_root" "$p" "$canon"
'

# parcourir COMPTE : lance PARCOURS sous l'uid COMPTE et range sa réponse
# dans CHAMPS, un champ par élément ; CHAMPS[0] est vide si docker exec
# échoue.
parcourir() {
  local resultat
  resultat=$(docker exec -u "$1" "${CONTAINER}" \
    sh -c "${PARCOURS}" sh "${DEST_DIR}") || resultat=""
  mapfile -t CHAMPS <<<"${resultat}"
}

# Chaque compte essayé parcourt la destination ; un parcours arrêté par un
# répertoire se reprend sous le propriétaire de ce répertoire, s'il n'a pas
# déjà été essayé. COMPTE reste le compte du parcours retenu.
ESSAYES=()
COMPTE="${CODE_OWNER}"
CHAMPS=()
for _ in 1 2 3; do
  ESSAYES+=("${COMPTE}")
  parcourir "${COMPTE}"
  if [[ "${CHAMPS[0]}" != "blocked" ]] ||
    [[ ! "${CHAMPS[1]:-}" =~ ^[0-9]+$ ]] ||
    [[ " ${ESSAYES[*]} " == *" ${CHAMPS[1]} "* ]]; then
    break
  fi
  COMPTE="${CHAMPS[1]}"
done

case "${CHAMPS[0]}" in
ok)
  ANCETRE_UID="${CHAMPS[1]:-}"
  ANCETRE_MODE="${CHAMPS[2]:-}"
  TOUT_ROOT="${CHAMPS[3]:-}"
  ANCETRE="${CHAMPS[4]:-}"
  CANON="${CHAMPS[5]:-}"
  ;;
notdir)
  echo "Error: '${CHAMPS[2]:-}' exists in the container and is not a directory."
  exit 1
  ;;
blocked)
  echo "Error: no account tried (uid ${ESSAYES[*]}) can traverse" \
    "'${CHAMPS[2]:-}' in the container."
  exit 1
  ;;
*)
  echo "Error: cannot inspect '${DEST_DIR}' in the container."
  exit 1
  ;;
esac
# Ces champs viennent du conteneur et entrent dans une expression
# arithmétique, dans docker exec -u et dans le chemin écrit : seuls des
# entiers et un chemin absolu passent.
if [[ ! "${ANCETRE_UID}" =~ ^[0-9]+$ ]] ||
  [[ ! "${ANCETRE_MODE}" =~ ^[0-7]+$ ]] ||
  [[ "${CANON}" != /* ]]; then
  echo "Error: unexpected answer from the container for '${DEST_DIR}'."
  exit 1
fi

# Root n'écrit que sur un parcours fait sous root : sinon, il se refait sous
# root, qui doit rendre le même chemin canonique et un ancêtre à lui. Ses
# champs remplacent alors ceux du premier parcours ; une réponse différente
# ou invalide laisse l'écriture au propriétaire de /ERPLibre.
if [[ "${ANCETRE_UID}" == 0 ]] && [[ "${COMPTE}" != 0 ]]; then
  parcourir 0
  if [[ "${CHAMPS[0]}" == ok ]] && [[ "${CHAMPS[1]:-}" == 0 ]] &&
    [[ "${CHAMPS[2]:-}" =~ ^[0-7]+$ ]] &&
    [[ "${CHAMPS[5]:-}" == "${CANON}" ]]; then
    ANCETRE_MODE="${CHAMPS[2]}"
    TOUT_ROOT="${CHAMPS[3]:-}"
    ANCETRE="${CHAMPS[4]:-}"
  else
    TOUT_ROOT=0
  fi
fi

# Les deux derniers chiffres du mode octal : le groupe et les autres.
DROITS_AUTRES=$((8#${ANCETRE_MODE} & 8#022))
ECRIVAIN="${ANCETRE_UID}"
if [[ "${ECRIVAIN}" == 0 ]] &&
  { [[ "${TOUT_ROOT}" != 1 ]] || [[ "${DROITS_AUTRES}" != 0 ]]; }; then
  ECRIVAIN="${CODE_OWNER}"
fi

echo "Copying '${SRC_FILE}' to '${CONTAINER}:${CANON}/${SRC_BASENAME}'" \
  "as uid ${ECRIVAIN}"
# shellcheck disable=SC2016
if ! docker exec -i -u "${ECRIVAIN}" "${CONTAINER}" \
  sh -c 'umask 022 && mkdir -p -- "$1" && cat >"$1/$2"' \
  sh "${CANON}" "${SRC_BASENAME}" <"${SRC_FILE}"; then
  echo "Error: uid ${ECRIVAIN} cannot write '${CANON}/${SRC_BASENAME}'" \
    "under '${ANCETRE}', owned by uid ${ANCETRE_UID}."
  exit 1
fi

echo "File copy complete."
