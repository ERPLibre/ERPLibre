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
# Chacune porte une exigence pip par mot : « humanize pyotp==2.9.0
# phonenumbers>=8.13,<9 ». Une contrainte de version ne contient ni espace ni
# guillemet : la valeur se coupe aux espaces et aux retours à la ligne, ceux
# d'un bloc YAML sur plusieurs lignes compris, et rien d'autre ne
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
#
# APT_EXTRA_PACKAGES porte des paquets Debian, un nom par mot, coupé comme
# les listes pip : les bibliothèques système qu'un paquet pip charge
# (« libmagic1 » pour python-magic), ou un navigateur pour Selenium. apt les
# installe en root, avant les listes pip, et avant que le script ne cède la
# main à odoo : root ne reçoit que des noms, validés, jamais une commande ni
# un fichier du code, qu'Odoo peut réécrire. Un nom déjà installé, ou fourni
# par un paquet installé (Provides), ne déclenche rien, ni réseau ni apt-get
# update.
#
# apt-get install lit un mot autrement que comme un nom dans trois cas : un
# « - » final retire le paquet, un « + » final est une action, et un nom
# qu'aucun paquet ne porte devient une expression régulière (« . » y est un
# joker). Il installe alors autre chose que le nom demandé, ou rien, et le
# nom reste absent de dpkg : chaque démarrage relance apt, et sans réseau,
# avec « restart: always », le conteneur redémarre en boucle. Le script
# refuse donc, avant apt-get install, un nom qui finit par « - » ou par un
# seul « + » (« g++ » passe), puis, après apt-get update, un nom que l'index
# d'apt ne connaît pas tel quel ; après l'installation, il vérifie que
# chaque nom est installé ou fourni.
#
# apt demande à root CHOWN, DAC_OVERRIDE, FOWNER et FSETID en plus de
# SETUID et SETGID. Sans CHOWN, DAC_OVERRIDE ou FOWNER, apt échoue ; sans
# FSETID, il réussit, mais un binaire setgid perd son bit, sans erreur. Le
# script les vérifie donc toutes avant apt, et s'arrête si l'une manque.
# setpriv les retire au passage à odoo, et no-new-privileges empêche Odoo
# de les regagner.

set -euo pipefail

prefixe="${ODOO_PREFIX:-/ERPLibre}"
compte="${ERPLIBRE_RUN_AS:-odoo}"
suite="${ERPLIBRE_ENTRYPOINT:-/entrypoint.sh}"
# Les tests le pointent sur un faux fichier d'état de processus.
etat_processus="${ERPLIBRE_PROC_STATUS:-/proc/self/status}"

# Masque des capacités qu'apt exige en plus de SETUID et SETGID :
# CHOWN (bit 0), DAC_OVERRIDE (1), FOWNER (3), FSETID (4).
CAPS_APT=$(((1 << 0) | (1 << 1) | (1 << 3) | (1 << 4)))

# deja_installe PAQUET : vrai si PAQUET est installé, ou fourni par un
# paquet installé — « libmagic1 » l'est par « libmagic1t64 » sous trixie.
deja_installe() {
  dpkg-query -W -f='${db:Status-Abbrev} ${Package} ${Provides}\n' \
    2>/dev/null | awk -v p="$1" '
      $1 == "ii" {
        for (i = 2; i <= NF; i++) { n = $i; sub(/[(,].*/, "", n); if (n == p) t = 1 }
      }
      END { exit !t }'
}

# connu_d_apt PAQUET : vrai si l'index d'apt porte le nom PAQUET tel quel,
# paquet réel ou virtuel. « pkgnames » compare un préfixe, sans expression
# régulière ; awk lit toute la sortie, donc aucun SIGPIPE ne fait échouer
# apt-cache sous pipefail. Un nom virtuel sans fournisseur passe : apt-get
# install le refuse ensuite avec une erreur.
connu_d_apt() {
  apt-cache --all-names pkgnames "$1" |
    awk -v p="$1" '$0 == p { t = 1 } END { exit !t }'
}

# vider_cache_apt : retire de la couche du conteneur les .deb téléchargés et
# les listes d'apt-get update. C'est du ménage : un échec avertit, et Odoo
# démarre quand même.
vider_cache_apt() {
  local sortie listes=""
  if ! { apt-get clean &&
    sortie=$(apt-config shell listes Dir::State::lists/d) &&
    eval "${sortie}" &&
    if [[ -n "${listes}" && -d "${listes}" ]]; then
      find "${listes}" -mindepth 1 -delete
    fi; }; then
    echo "Avertissement : le cache d'apt reste dans la couche du conteneur." >&2
  fi
}

# installer_apt : installe APT_EXTRA_PACKAGES en root ; sort en 1, Odoo non
# lancé, sur un nom invalide ou inconnu d'apt, sans root ou sans les
# capacités d'apt, si apt refuse, ou si un nom reste absent après apt.
installer_apt() {
  local paquets=() manquants=() p capeff
  read -r -d '' -a paquets <<<"${APT_EXTRA_PACKAGES:-}" || true
  ((${#paquets[@]})) || return 0
  for p in "${paquets[@]}"; do
    # Un nom Debian : ni option (« -o … »), ni version, ni chemin, ni
    # suffixe d'action d'apt — « - » final, ou « + » final seul.
    if [[ ! "${p}" =~ ^[a-z0-9][a-z0-9+.-]*([a-z0-9]|\+\+)$ ]]; then
      echo "Erreur : « ${p} » n'est pas un nom de paquet Debian (APT_EXTRA_PACKAGES) ; Odoo ne démarre pas." >&2
      exit 1
    fi
    deja_installe "${p}" || manquants+=("${p}")
  done
  if ! ((${#manquants[@]})); then
    echo "apt extra : déjà installés (${paquets[*]})"
    return 0
  fi
  if [[ "$(id -u)" != 0 ]]; then
    echo "Erreur : APT_EXTRA_PACKAGES s'installe en root (« user: root » du compose) ; Odoo ne démarre pas." >&2
    exit 1
  fi
  capeff=$(awk '/^CapEff:/ { print $2 }' "${etat_processus}")
  if (((16#${capeff:-0} & CAPS_APT) != CAPS_APT)); then
    echo "Erreur : APT_EXTRA_PACKAGES demande au compose « cap_add: [SETUID, SETGID, CHOWN, DAC_OVERRIDE, FOWNER, FSETID] » ; Odoo ne démarre pas." >&2
    exit 1
  fi
  echo "apt extra : ${manquants[*]}"
  if ! apt-get update -q; then
    echo "Erreur : apt n'a pas installé APT_EXTRA_PACKAGES ; Odoo ne démarre pas." >&2
    exit 1
  fi
  for p in "${manquants[@]}"; do
    if ! connu_d_apt "${p}"; then
      vider_cache_apt
      echo "Erreur : apt ne connaît aucun paquet « ${p} » (APT_EXTRA_PACKAGES) ; Odoo ne démarre pas." >&2
      exit 1
    fi
  done
  if ! DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    --no-install-recommends "${manquants[@]}"; then
    echo "Erreur : apt n'a pas installé APT_EXTRA_PACKAGES ; Odoo ne démarre pas." >&2
    exit 1
  fi
  vider_cache_apt
  for p in "${manquants[@]}"; do
    if ! deja_installe "${p}"; then
      echo "Erreur : apt a fini sans installer « ${p} » (APT_EXTRA_PACKAGES) ; Odoo ne démarre pas." >&2
      exit 1
    fi
  done
}

# installer VARIABLE PYTHON : pip installe la liste de VARIABLE avec PYTHON,
# sous le propriétaire du venv quand le script tourne en root ; sort en 1,
# Odoo non lancé, si pip refuse.
installer() {
  local variable="$1" python="$2" exigences venv sous=()
  read -r -d '' -a exigences <<<"${!variable:-}" || true
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

installer_apt
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
