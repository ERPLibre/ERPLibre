#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Navigateur des tests navigateur d'Odoo : tours, hoot, et tout HttpCase qui
# passe par browser_js ou start_tour.
#
# Odoo cherche ce navigateur dans le PATH, dans cet ordre : google-chrome,
# chromium, chromium-browser, google-chrome-stable ; sur macOS, Google
# Chrome.app puis Chromium.app sous /Applications. Quand aucun ne répond,
# chaque test navigateur lève SkipTest : la passe finit verte et seul
# « Chrome executable not found » au journal dit que rien n'a tourné. Le
# paquet Python websocket-client, absent du venv d'Odoo, produit le même saut
# silencieux ; ce script le vérifie aussi, sans l'installer.
#
# Hors de « make install_os » : un navigateur complet pèse plusieurs centaines
# de Mo et ne sert à rien sur un serveur de production, qui passe aussi par
# install_dev.sh. Cible dédiée : « make install_browser_test ».
#
# Idempotent : un navigateur déjà trouvé par la recherche d'Odoo n'est pas
# réinstallé, sauf un Chromium snap, que les tests ne savent pas piloter et
# qui ne compte donc pas comme présent.
#
#   ./script/install/install_browser_test.sh [--dry-run]
#
# --dry-run affiche les commandes sans les exécuter. EL_OS_RELEASE, EL_UNAME_S
# et EL_UNAME_M remplacent /etc/os-release et uname : en --dry-run, le script
# n'appelle alors que des commandes internes de bash. Hors --dry-run, il
# appelle aussi readlink pour résoudre les liens des navigateurs trouvés.

EL_DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  EL_DRY_RUN=1
elif [[ -n "${1:-}" ]]; then
  echo "Option inconnue : ${1}. Usage : $0 [--dry-run]" >&2
  exit 2
fi

EL_OS_RELEASE="${EL_OS_RELEASE:-/etc/os-release}"
EL_UNAME_S="${EL_UNAME_S:-$(uname -s)}"
EL_UNAME_M="${EL_UNAME_M:-$(uname -m)}"

APT_GET="sudo apt-get -o DPkg::Lock::Timeout=600"
# Le .deb officiel de Google : il dépose aussi le dépôt apt de Google, par
# lequel le navigateur suit ensuite les mises à jour du système.
CHROME_DEB_URL="https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"

# Exécute la commande, ou l'affiche en --dry-run, mots protégés par %q pour
# qu'elle se recopie telle quelle.
el_run() {
  if [[ ${EL_DRY_RUN} -eq 1 ]]; then
    printf '%q ' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

# Vrai quand le navigateur au chemin $1 est un Chromium snap : un chemin sous
# /snap/ ou sous un répertoire snap/bin, un lien qui y mène (résolu par
# readlink, hors --dry-run seulement), ou un script qui renvoie au snap,
# comme le « chromium-browser » de transition d'Ubuntu. Le snap a son propre
# /tmp : Odoo crée le profil du navigateur sous /tmp et y attend le fichier
# DevToolsActivePort, que le snap écrit dans le sien.
el_is_snap() {
  local path_="$1" real_="" first_="" content_=""
  if [[ "${path_}" == /snap/* || "${path_}" == */snap/bin/* ]]; then
    return 0
  fi
  if [[ ${EL_DRY_RUN} -eq 0 ]]; then
    real_="$(readlink -f "${path_}" 2> /dev/null)"
    [[ "${real_}" == /snap/* ]] && return 0
  fi
  # Seul un script est lu : un binaire peut porter « /snap/ » dans ses
  # chaînes sans rien devoir au snap.
  [[ -f "${path_}" && -r "${path_}" ]] || return 1
  IFS= read -r -n 2 first_ < "${path_}" || [[ -n "${first_}" ]] || return 1
  [[ "${first_}" == "#!" ]] || return 1
  content_="$(< "${path_}")"
  [[ "${content_}" == *"/snap/"* ]]
}

# Rend sur stdout le premier navigateur que trouverait Odoo, hors snap, code 1
# sinon. Chaque snap écarté s'annonce sur stderr, stdout ne portant que le
# navigateur retenu.
el_find_browser() {
  local bin_
  if [[ "${EL_UNAME_S}" == "Darwin" ]]; then
    for bin_ in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      "/Applications/Chromium.app/Contents/MacOS/Chromium"; do
      if [[ -x "${bin_}" ]]; then
        echo "${bin_}"
        return 0
      fi
    done
    return 1
  fi
  local path_
  for bin_ in google-chrome chromium chromium-browser google-chrome-stable; do
    path_="$(command -v "${bin_}" 2> /dev/null)" || continue
    if el_is_snap "${path_}"; then
      echo "Navigateur snap ecarte, les tests d'Odoo ne savent pas le piloter : ${path_}" >&2
      continue
    fi
    echo "${path_}"
    return 0
  done
  return 1
}

# Le .deb de Google, seule voie propre sur Ubuntu : son « chromium-browser »
# n'est qu'un paquet de transition vers le snap (voir el_is_snap), où le test
# saute sur « Failed to detect chrome devtools port ». Google ne publie ce
# .deb que pour amd64.
el_install_chrome_deb() {
  if [[ "${EL_UNAME_M}" != "x86_64" ]]; then
    echo "Aucun paquet propre sur ${ID} ${EL_UNAME_M} : le chromium d'apt y est un"
    echo "snap, que les tests d'Odoo ne savent pas piloter, et Google Chrome n'existe"
    echo "qu'en amd64. Placer dans le PATH un Chromium hors snap, puis relancer."
    return 1
  fi
  # Le .deb est lu par apt en root : un répertoire neuf, propre à l'appel, et
  # retiré quel que soit le résultat.
  local deb_dir="<repertoire_temporaire>" status=0
  if [[ ${EL_DRY_RUN} -eq 0 ]]; then
    deb_dir="$(mktemp -d)" || return 1
  fi
  el_run wget -q -O "${deb_dir}/google-chrome-stable.deb" "${CHROME_DEB_URL}" \
    && el_run ${APT_GET} update \
    && el_run ${APT_GET} install -y "${deb_dir}/google-chrome-stable.deb" \
    || status=1
  [[ ${EL_DRY_RUN} -eq 1 ]] || rm -rf "${deb_dir}"
  return ${status}
}

# Pose le navigateur selon la distribution, avec la même lecture de
# /etc/os-release qu'install_dev.sh. Code 1 quand rien n'a pu être posé.
el_install_browser() {
  if [[ "${EL_UNAME_S}" == "Darwin" ]]; then
    el_run brew install --cask google-chrome
    return
  fi
  if [[ "${EL_UNAME_S}" != "Linux" || ! -r "${EL_OS_RELEASE}" ]]; then
    echo "Systeme non reconnu (uname -s = ${EL_UNAME_S}) : aucun navigateur pose."
    return 1
  fi
  local ID="" ID_LIKE=""
  # shellcheck disable=SC1090
  source "${EL_OS_RELEASE}"
  case "${ID}" in
    ubuntu)
      el_install_chrome_deb
      ;;
    debian | linuxmint)
      # Linux Mint bloque snapd et publie son propre « chromium » en .deb.
      el_run ${APT_GET} update || return 1
      el_run ${APT_GET} install -y chromium
      ;;
    arch)
      el_run sudo pacman -S --needed --noconfirm chromium
      ;;
    nixos)
      # Un paquet posé à la main vit hors de la déclaration et disparaît à la
      # reconstruction suivante : la déclaration revient à l'administrateur.
      echo "NixOS : ajouter « chromium » a environment.systemPackages puis"
      echo "« sudo nixos-rebuild switch », ou lancer les tests dans"
      echo "« nix-shell -p chromium ». Rien n'est pose par ce script."
      return 1
      ;;
    fedora)
      el_run sudo dnf install -y chromium
      ;;
    *)
      if [[ "${ID}" == opensuse* || "${ID_LIKE}" == *suse* ]]; then
        el_run sudo zypper --non-interactive install chromium
      elif [[ "${ID_LIKE}" == *rhel* || "${ID_LIKE}" == *fedora* ]]; then
        # Famille RHEL : chromium vit dans EPEL, qu'install_fedora_dependency.sh
        # active déjà ; le redemander ne coûte rien s'il l'est.
        el_run sudo dnf install -y epel-release
        el_run sudo dnf install -y chromium
      else
        echo "Distribution ${ID} non prise en charge : aucun navigateur pose."
        return 1
      fi
      ;;
  esac
}

# Le venv d'Odoo du checkout porte-t-il websocket-client ? Silencieux hors de
# la racine d'un checkout ERPLibre, où .erplibre-version n'existe pas.
el_check_websocket() {
  [[ -r .erplibre-version ]] || return 0
  local version venv_python
  version="$(< .erplibre-version)"
  venv_python=".venv.${version//[[:space:]]/}/bin/python"
  [[ -x "${venv_python}" ]] || return 0
  if "${venv_python}" -c "import websocket" 2> /dev/null; then
    echo "websocket-client present dans ${venv_python}."
    return 0
  fi
  echo "websocket-client ABSENT de ${venv_python} : les tests navigateur"
  echo "sauteront quand meme. Depuis la racine du depot :"
  echo "  source .venv.${version//[[:space:]]/}/bin/activate && poetry install --no-root"
  echo "Si poetry repond que poetry.lock ne correspond plus a pyproject.toml,"
  echo "lancer « poetry lock » avant, dans le meme venv."
  return 1
}

main() {
  local found status=0
  if found="$(el_find_browser)"; then
    echo "Navigateur des tests deja present : ${found}"
  else
    echo -e "\n---- Navigateur des tests Odoo (tours, hoot) ----"
    el_install_browser || return 1
    if [[ ${EL_DRY_RUN} -eq 0 ]]; then
      if ! found="$(el_find_browser)"; then
        echo "Installation terminee, mais aucun navigateur trouve dans le PATH."
        return 1
      fi
      echo "Navigateur des tests : ${found}"
    fi
  fi
  el_check_websocket || status=1
  return ${status}
}

main
