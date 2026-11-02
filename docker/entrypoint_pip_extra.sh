#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Point d'entrée d'un conteneur ERPLibre qui installe des dépendances Python
# en plus de celles de l'image, puis passe la main à /entrypoint.sh.
#
# Deux listes, une par venv de l'image :
#   PIP_EXTRA_REQUIREMENTS_ODOO      venv d'Odoo (.venv.<.erplibre-version>),
#                                    celui qu'importent les addons
#   PIP_EXTRA_REQUIREMENTS_ERPLIBRE  venv des outils ERPLibre (.venv.erplibre),
#                                    celui des scripts de script/
# Chacune porte une exigence pip par mot, sur une ligne : « humanize
# pyotp==2.9.0 phonenumbers>=8.13,<9 ». Une contrainte de version ne contient
# ni espace ni guillemet : la ligne se coupe aux espaces, rien d'autre ne
# l'interprète. Vide ou absente, rien ne s'installe dans ce venv.
#
# Chaque pip résout sa liste contre ce que son venv porte déjà, et une
# exigence satisfaite ne télécharge rien. Une installation refusée arrête le
# conteneur avant Odoo, plutôt que de laisser un addon ou un script échouer à
# l'import ; la liste d'ERPLibre passe d'abord.
#
# Les venvs appartiennent au propriétaire du code de l'image, « odoo » ou
# « root » selon ERPLIBRE_CODE_OWNER à la construction. Lancé en root
# (« user: root » du compose), le script fait tourner chaque pip sous le
# propriétaire de son venv : un fichier posé par root dans un venv d'odoo
# bloquerait la réinstallation des dépendances qui suit un tirage. Il
# s'exécute ensuite sous le compte odoo par setpriv ; après l'exec, aucun
# processus du conteneur ne tourne plus en root. Lancé sous un autre compte,
# il installe s'il le peut et garde ce compte. USER reste intact :
# l'entrypoint de l'image y lit l'utilisateur PostgreSQL.
#
# L'installation vit dans la couche du conteneur : un redémarrage la garde,
# une recréation la refait au démarrage suivant.

set -euo pipefail

prefixe="${ODOO_PREFIX:-/ERPLibre}"
compte="${ERPLIBRE_RUN_AS:-odoo}"
suite="${ERPLIBRE_ENTRYPOINT:-/entrypoint.sh}"

# installer VARIABLE PYTHON : pip installe la liste de VARIABLE avec PYTHON,
# sous le propriétaire du venv quand le script tourne en root ; sort en 1,
# Odoo non lancé, si pip refuse.
installer() {
  local variable="$1" python="$2" exigences venv sous=()
  read -ra exigences <<<"${!variable:-}"
  ((${#exigences[@]})) || return 0
  venv="$(dirname "$(dirname "${python}")")"
  if [[ "$(id -u)" == 0 && "$(stat -c %u "${venv}")" != 0 ]]; then
    sous=(setpriv --reuid="$(stat -c %u "${venv}")"
      --regid="$(stat -c %g "${venv}")" --clear-groups
      env HOME="$(getent passwd "$(stat -c %u "${venv}")" | cut -d: -f6)")
  fi
  echo "pip extra (${python}) : ${exigences[*]}"
  if ! "${sous[@]}" "${python}" -m pip install --disable-pip-version-check \
    --no-input --no-cache-dir "${exigences[@]}"; then
    echo "Erreur : pip n'a pas installé ${variable} ; Odoo ne démarre pas." >&2
    exit 1
  fi
}

installer PIP_EXTRA_REQUIREMENTS_ERPLIBRE "${prefixe}/.venv.erplibre/bin/python"
if [[ -n "${PIP_EXTRA_REQUIREMENTS_ODOO:-}" ]]; then
  version=$(tr -d '[:space:]' <"${prefixe}/.erplibre-version")
  installer PIP_EXTRA_REQUIREMENTS_ODOO "${prefixe}/.venv.${version}/bin/python"
fi

if [[ "$(id -u)" == 0 && "${compte}" != root ]]; then
  exec setpriv --reuid="$(id -u "${compte}")" --regid="$(id -g "${compte}")" \
    --init-groups env HOME="$(getent passwd "${compte}" | cut -d: -f6)" \
    "${suite}" "$@"
fi
exec "${suite}" "$@"
