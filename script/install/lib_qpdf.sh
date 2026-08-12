#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque SOURÇABLE : garantir un qpdf assez récent pour pikepdf.
#
# pikepdf 10 déclare QPDF_MIN_VERSION = "12.2.0" et se lie à la bibliothèque
# C++ de la distribution. Là où PyPI publie une roue, rien de tout cela ne
# s'exécute ; sur s390x il n'y en a aucune, pikepdf compile, et une version
# trop ancienne le fait échouer sur des en-têtes qui n'existent pas encore
# (« qpdf/QPDFJob.hh », apparu en 10.6 ; « qpdf/QPDFLogger.hh », en 11.0) puis
# sur des constantes renommées. Le message ne nomme jamais qpdf : on lit trois
# cents lignes de g++ avant de comprendre.
#
# Aucune famille n'est à jour partout, d'où le seuil plutôt qu'une liste de
# distributions : Ubuntu 24.04 livre 11.9, AlmaLinux et Rocky 9 livrent 10.3
# (sans même QPDFJob.hh), leurs 10 livrent 11.9 ; Ubuntu 25.10, Fedora 43 et
# Tumbleweed dépassent le seuil et ne compilent rien.
#
# Ce fichier existe parce que le bloc vivait en double : corrigé côté apt, il
# ne l'était pas côté dnf, et EL9 est ressorti sur exactement le même mur le
# lendemain. Le seuil, la version et la façon de bâtir sont désormais écrits
# UNE fois pour les trois familles de paquets.

EL_QPDF_MIN=12.2.0
EL_QPDF_VER=12.3.2

# Vrai si la version passée en argument atteint le seuil. « sort -V » est le
# seul comparateur de versions disponible partout sans dépendance, mais il
# classe « 12.2 » AVANT « 12.2.0 » — un paquet numéroté sur deux composantes
# aurait donc déclenché une compilation d'une demi-heure pour rien. On complète
# les composantes manquantes avant de comparer.
el_qpdf_ge_min() {
  local v="$1" dots
  [ -n "${v}" ] || return 1
  dots="${v//[^.]/}"
  while [ "${#dots}" -lt 2 ]; do
    v="${v}.0"
    dots="${dots}."
  done
  [ "$(printf '%s\n%s\n' "${EL_QPDF_MIN}" "${v}" | sort -V | head -1)" = "${EL_QPDF_MIN}" ]
}

# Version actuellement visible du compilateur, ou « 0 ».
# /usr/local n'est pas dans le chemin par défaut de pkg-config sur toutes les
# familles : sans ces deux entrées, un qpdf déjà compilé passerait inaperçu et
# on le recompilerait à chaque passage du script.
el_qpdf_version() {
  PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib64/pkgconfig:${PKG_CONFIG_PATH}" \
    pkg-config --modversion libqpdf 2> /dev/null || echo 0
}

# Compile et installe qpdf dans /usr/local si, et seulement si, ce qui est
# présent ne suffit pas. Ne rend jamais un code non nul : l'échec est signalé
# et l'installation continue, pikepdf dira lui-même ce qui manque.
el_qpdf_ensure() {
  local have build dir
  have="$(el_qpdf_version)"
  if el_qpdf_ge_min "${have}"; then
    echo "qpdf ${have} >= ${EL_QPDF_MIN} : rien a compiler pour pikepdf."
    return 0
  fi

  echo "qpdf ${have} < ${EL_QPDF_MIN} requis par pikepdf : compilation de qpdf ${EL_QPDF_VER} (long en emulation)."
  build="$(mktemp -d)"
  if curl -fsSL --max-time 600 -o "${build}/qpdf.tar.gz" \
    "https://github.com/qpdf/qpdf/releases/download/v${EL_QPDF_VER}/qpdf-${EL_QPDF_VER}.tar.gz" \
    && tar -xzf "${build}/qpdf.tar.gz" -C "${build}" \
    && cmake -S "${build}/qpdf-${EL_QPDF_VER}" -B "${build}/build" \
      -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local \
      -DBUILD_DOC=OFF -DBUILD_STATIC_LIBS=OFF \
    && cmake --build "${build}/build" -j"$(nproc)" \
    && sudo cmake --install "${build}/build"; then
    # CMake choisit « lib » ou « lib64 » selon la famille, et /usr/local/lib64
    # n'est pas dans le chemin de ld.so d'EL : sans cette déclaration, pikepdf
    # se construirait pour échouer au CHARGEMENT, encore plus loin de la cause.
    for dir in /usr/local/lib64 /usr/local/lib; do
      if [ -e "${dir}/libqpdf.so" ]; then
        echo "${dir}" | sudo tee /etc/ld.so.conf.d/qpdf-local.conf > /dev/null
        break
      fi
    done
    sudo ldconfig
    echo "qpdf $(el_qpdf_version) installe dans /usr/local."
  else
    echo "Attention : compilation de qpdf echouee, pikepdf ne pourra pas se construire."
  fi
  rm -rf "${build}"
}
