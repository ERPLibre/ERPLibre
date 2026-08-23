#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# PROJ assez récent pour pyproj, compilé depuis les sources quand la
# distribution est en retard. Calque de lib_qpdf.sh, pour la même raison et
# avec les mêmes garde-fous.
#
# QUI est concerné, et qui ne l'est pas : sur amd64 et arm64, pyproj publie
# des roues manylinux qui EMBARQUENT leur propre PROJ — rien n'est compilé et
# la version du système n'a aucune importance. s390x n'a pas de roue : pyproj
# se construit contre la PROJ du système, et refuse net si elle est trop
# vieille.
#
#   ERROR: Minimum supported PROJ version is 9.4.0, installed version is 9.1.1
#
# Mesuré sur Debian 12 (bookworm) s390x. Debian 13 livre 9.6 et passe sans
# rien faire ; ce fichier ne s'y déclenche donc pas.

# Seuil réclamé par pyproj 3.7.x. Le monter suppose de vérifier ce qu'exige la
# version de pyproj réellement verrouillée dans poetry.lock.
EL_PROJ_MIN=9.4.0
# Version bâtie quand le seuil n'est pas atteint. 9.6.x est la branche stable
# la plus récente à ce jour et couvre largement le seuil.
EL_PROJ_VER=9.6.2

# Vrai si la version passée en argument atteint le seuil. Même précaution que
# pour qpdf : « sort -V » classe « 9.4 » AVANT « 9.4.0 », donc une version
# numérotée sur deux composantes déclencherait une compilation inutile — et
# celle de PROJ se compte en dizaines de minutes sous émulation.
el_proj_ge_min() {
  local v="$1" dots
  [ -n "${v}" ] || return 1
  dots="${v//[^.]/}"
  while [ "${#dots}" -lt 2 ]; do
    v="${v}.0"
    dots="${dots}."
  done
  [ "$(printf '%s\n%s\n' "${EL_PROJ_MIN}" "${v}" | sort -V | head -1)" = "${EL_PROJ_MIN}" ]
}

# Version actuellement visible, ou « 0 ». /usr/local n'est pas dans le chemin
# par défaut de pkg-config partout : sans ces entrées, une PROJ déjà compilée
# passerait inaperçue et serait rebâtie à chaque passage.
el_proj_version() {
  PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib64/pkgconfig:${PKG_CONFIG_PATH}" \
    pkg-config --modversion proj 2> /dev/null || echo 0
}

# Compile et installe PROJ dans /usr/local si, et seulement si, ce qui est
# présent ne suffit pas. Ne rend jamais un code non nul : l'échec est signalé
# et l'installation continue, pyproj dira lui-même ce qui manque.
el_proj_ensure() {
  local have build dir
  have="$(el_proj_version)"
  if el_proj_ge_min "${have}"; then
    echo "PROJ ${have} >= ${EL_PROJ_MIN} : rien a compiler pour pyproj."
    return 0
  fi

  echo "PROJ ${have} < ${EL_PROJ_MIN} requis par pyproj : compilation de PROJ ${EL_PROJ_VER} (long en emulation)."
  build="$(mktemp -d)"
  # TESTING=OFF et les outils en moins : seule la bibliothèque intéresse
  # pyproj, et la suite de tests de PROJ double le temps de compilation.
  if curl -fsSL --max-time 900 -o "${build}/proj.tar.gz" \
    "https://download.osgeo.org/proj/proj-${EL_PROJ_VER}.tar.gz" \
    && tar -xzf "${build}/proj.tar.gz" -C "${build}" \
    && cmake -S "${build}/proj-${EL_PROJ_VER}" -B "${build}/build" \
      -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local \
      -DBUILD_TESTING=OFF -DBUILD_APPS=ON -DBUILD_SHARED_LIBS=ON \
    && cmake --build "${build}/build" -j"$(nproc)" \
    && sudo cmake --install "${build}/build"; then
    # CMake choisit « lib » ou « lib64 » selon la famille, et /usr/local/lib64
    # n'est pas dans le chemin de ld.so partout : sans cette déclaration,
    # pyproj se construirait pour échouer au CHARGEMENT, plus loin de la cause.
    for dir in /usr/local/lib64 /usr/local/lib; do
      if [ -e "${dir}/libproj.so" ]; then
        echo "${dir}" | sudo tee /etc/ld.so.conf.d/proj-local.conf > /dev/null
        break
      fi
    done
    sudo ldconfig
    echo "PROJ $(el_proj_version) installe dans /usr/local."
  else
    echo "Attention : compilation de PROJ echouee, pyproj ne pourra pas se construire."
  fi
  rm -rf "${build}"
  return 0
}
