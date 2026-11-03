#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Tient les skills d'agent d'Odoo (« skills/ » du dépôt odoo/odoo) à jour dans
# « .claude/skills/odoo-* », sans jamais cloner le dépôt entier.
#
# Usage :
#   sync_odoo_skills.sh                 installe la tête de la branche suivie
#   sync_odoo_skills.sh --check         montre ce qui a changé en amont, n'écrit rien
#   sync_odoo_skills.sh --ref <réf>     installe une branche ou un commit précis
#   sync_odoo_skills.sh --save-patch    régénère erplibre.patch depuis la copie installée
#
# La copie installée = l'amont au commit noté dans conf/odoo_skills/UPSTREAM,
# plus conf/odoo_skills/erplibre.patch, plus les ERPLIBRE.md qui n'existent
# qu'ici. Le patch reste minime : ce qui diffère pour ERPLibre ou pour une
# version d'Odoo antérieure vit dans les ERPLIBRE.md, que la synchronisation ne
# touche pas. Une mise à niveau se réduit donc à relire le diff amont.
#
# Un clone partiel (--filter=blob:none, sparse « /skills/ », profondeur 1)
# ne rapatrie que les arbres et les blobs de skills/ : quelques Mo.
#
# L'installation se monte entière dans un répertoire temporaire et ne remplace
# la copie installée qu'une fois le patch appliqué : un patch qui ne s'applique
# plus arrête tout, sans rien laisser à moitié écrit.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONF="${ROOT}/conf/odoo_skills"
DEST="${ROOT}/.claude/skills"
UPSTREAM_FILE="${CONF}/UPSTREAM"
PATCH="${CONF}/erplibre.patch"
# odoo-git y est : elle porte les conventions de commit des dépôts Odoo et OCA,
# et sa description patchée la limite à ces dépôts.
SKILLS=(odoo-guidelines odoo-web-guidelines odoo-review odoo-security odoo-git)
# Fichiers propres à ERPLibre dans un répertoire de skill : la synchronisation
# les conserve tels quels.
LOCAL_FILES=(ERPLIBRE.md)

MODE="install"
REF=""
while [ $# -gt 0 ]; do
    case "$1" in
    --check) MODE="check" ;;
    --save-patch) MODE="save-patch" ;;
    --ref)
        REF="${2:?--ref attend une branche ou un commit}"
        shift
        ;;
    -h | --help)
        sed -n '5,12p' "$0" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    *)
        echo "Option inconnue : $1" >&2
        exit 2
        ;;
    esac
    shift
done

# UPSTREAM : lignes « clé=valeur » (repository, branch, commit, date).
upstream_get() {
    sed -n "s/^$1=//p" "${UPSTREAM_FILE}"
}
REPOSITORY="$(upstream_get repository)"
BRANCH="$(upstream_get branch)"
PINNED="$(upstream_get commit)"

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
SRC="${WORK}/odoo"

# Rapatrie <réf> dans SRC, réduit à skills/. Une branche comme un SHA complet
# passent par « fetch » : GitHub sert un commit par son SHA.
fetch_ref() {
    git -C "${SRC}" fetch -q --depth 1 --filter=blob:none origin "$1"
}
git init -q "${SRC}"
git -C "${SRC}" remote add origin "${REPOSITORY}"
git -C "${SRC}" sparse-checkout set --no-cone /skills/

# Monte dans <dossier>/.claude/skills la copie amont du commit courant de SRC,
# ERPLIBRE.md exclus : ils n'existent pas en amont.
stage_upstream() {
    local into="$1/.claude/skills"
    mkdir -p "${into}"
    for skill in "${SKILLS[@]}"; do
        if [ ! -d "${SRC}/skills/${skill}" ]; then
            echo "Absente en amont : ${skill}. Retirer de SKILLS ou suivre le renommage." >&2
            exit 1
        fi
        cp -r "${SRC}/skills/${skill}" "${into}/${skill}"
    done
}

if [ "${MODE}" = "save-patch" ]; then
    # Le patch se mesure contre le commit NOTÉ, pas contre la tête : c'est sur
    # lui que la copie installée repose.
    fetch_ref "${PINNED}"
    git -C "${SRC}" checkout -q FETCH_HEAD
    stage_upstream "${WORK}/a"
    mkdir -p "${WORK}/b/.claude/skills"
    for skill in "${SKILLS[@]}"; do
        cp -r "${DEST}/${skill}" "${WORK}/b/.claude/skills/${skill}"
        for local_file in "${LOCAL_FILES[@]}"; do
            rm -f "${WORK}/b/.claude/skills/${skill}/${local_file}"
        done
    done
    # Sans préfixe, les chemins « a/.claude/… » et « b/.claude/… » sont déjà
    # ceux d'un patch -p1. --no-index rend 1 quand les arbres diffèrent : c'est
    # le cas attendu.
    (cd "${WORK}" && git diff --no-index --src-prefix= --dst-prefix= a b || true) >"${PATCH}"
    echo "Patch régénéré : ${PATCH#"${ROOT}"/} ($(grep -c '^diff --git' "${PATCH}") fichier(s))"
    exit 0
fi

TARGET="${REF:-${BRANCH}}"
fetch_ref "${TARGET}"
git -C "${SRC}" checkout -q FETCH_HEAD
NEW="$(git -C "${SRC}" rev-parse HEAD)"
NEW_DATE="$(git -C "${SRC}" log -1 --format=%cs HEAD)"

echo "Noté   : ${PINNED}"
echo "Amont  : ${NEW} (${TARGET}, ${NEW_DATE})"

# Une skill apparue en amont ne s'installe pas seule : elle peut contredire
# une règle ERPLibre, comme odoo-git avant d'être restreinte.
for dir in "${SRC}"/skills/*/; do
    name="$(basename "${dir}")"
    case " ${SKILLS[*]} " in
    *" ${name} "*) ;;
    *) echo "Nouvelle skill en amont, non installée : ${name}" ;;
    esac
done

if [ "${NEW}" = "${PINNED}" ]; then
    echo "Aucun changement en amont depuis le commit noté."
else
    fetch_ref "${PINNED}"
    if git -C "${SRC}" diff --quiet "${PINNED}" "${NEW}" -- skills/; then
        echo "La branche a avancé, mais skills/ n'a pas changé."
    else
        echo
        git -C "${SRC}" --no-pager diff --stat "${PINNED}" "${NEW}" -- skills/
        if [ "${MODE}" = "check" ]; then
            echo
            git -C "${SRC}" --no-pager diff "${PINNED}" "${NEW}" -- skills/
        fi
    fi
fi
[ "${MODE}" = "check" ] && exit 0

stage_upstream "${WORK}/stage"
# Un patch vide (aucune retouche) n'est pas un patch pour git apply.
if [ -s "${PATCH}" ] && ! (cd "${WORK}/stage" && git apply --whitespace=nowarn -p1 "${PATCH}"); then
    echo >&2
    echo "erplibre.patch ne s'applique plus sur ${NEW}. Rien n'a été modifié." >&2
    echo "Reporter les retouches à la main, puis --save-patch." >&2
    exit 1
fi

for skill in "${SKILLS[@]}"; do
    for local_file in "${LOCAL_FILES[@]}"; do
        if [ -f "${DEST}/${skill}/${local_file}" ]; then
            cp "${DEST}/${skill}/${local_file}" "${WORK}/stage/.claude/skills/${skill}/"
        fi
    done
    rm -rf "${DEST:?}/${skill}"
    mv "${WORK}/stage/.claude/skills/${skill}" "${DEST}/${skill}"
done
cp "${SRC}/skills/README.md" "${CONF}/README.upstream.md"

sed -i -e "s/^commit=.*/commit=${NEW}/" -e "s/^date=.*/date=${NEW_DATE}/" "${UPSTREAM_FILE}"
# Une branche passée à --ref devient la branche suivie ; un SHA, non.
if [ -n "${REF}" ] && ! [[ "${REF}" =~ ^[0-9a-f]{7,40}$ ]]; then
    sed -i "s/^branch=.*/branch=${REF}/" "${UPSTREAM_FILE}"
fi

echo
echo "Installé : ${NEW}. Relire le diff amont contre chaque ERPLIBRE.md :"
echo "une règle nouvelle ou changée peut ne pas valoir pour Odoo <= 18."
