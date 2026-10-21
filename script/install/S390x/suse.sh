#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Fragment SOURCÉ par install_suse_dependency.sh (openSUSE Leap et
# Tumbleweed), sur s390x seulement : swap, Rust, en-têtes de compilation,
# qpdf et libclang. Hérite de l'appelant zyp_soft et les variables
# d'env_var.sh ; un « exit » y arrête toute l'installation.

. ./script/install/S390x/lib_qpdf.sh
. ./script/install/S390x/lib_lowmem.sh
. ./script/install/S390x/lib_rust.sh

# La mémoire est la ressource qui manque en premier ici : cc1plus
# demande jusqu'à 2,5 Gio pour un seul fichier de matplotlib, et le
# tueur du noyau abrège sans jamais nommer la mémoire (« Killed signal
# terminated program cc1plus »). On complète par du swap avant d'en
# arriver là.
el_swap_ensure
zyp_soft rust cargo
if ! command -v cargo > /dev/null 2>&1; then
  # FATAL, et non plus un simple avertissement : sur s390x, bcrypt et
  # cryptography n'ont aucune roue et portent une extension Rust. Sans
  # cargo l'installation est perdue d'avance — mais elle ne le montrait
  # qu'une heure plus tard, au fond d'une trace pip. Mieux vaut s'arreter
  # ici, ou la cause est encore lisible.
  echo "cargo introuvable apres deux tentatives." >&2
  echo "  bcrypt et cryptography ne peuvent pas se compiler sans lui." >&2
  echo "  Verifiez le miroir zypper, puis relancez." >&2
  exit 1
fi
el_rust_ensure
# Sans roue s390x, TOUT se compile contre les en-têtes de la distribution.
# Cette liste reprend donc celles d'apt et de dnf, aux noms d'openSUSE près
# — pris dans l'index oss de zsystems, jamais devinés. Elle se tient
# alignée sur les autres distributions : un en-tête qui manque ici ne se
# découvre qu'à la compilation.
#   tbb-devel   manifold3d refuse de configurer sans lui, et le dit dans un
#               message de CMake, pas de compilateur : « Parallel mode
#               enabled, but tbb was not found ».
#   clang-devel pymupdf charge libclang.so par ctypes (lien juste après).
#   cmake, pkgconf-pkg-config : nécessaires à el_qpdf_ensure, et ils
#               n'arrivent que plus bas dans le script.
#
# « pkgconf-pkg-config » et non « pkg-config » : aucun RPM ne porte ce
# dernier nom dans Tumbleweed, il n'existe plus que comme capacité fournie
# par le premier. La capacité résout aujourd'hui, le nom réel ne dépend
# de rien.
#
# GeographicLib est absent : openSUSE n'empaquette que le binding Python,
# pas la bibliothèque C++. Rien à poser, contrairement à apt et dnf.
#   proj        le BINAIRE, pas seulement « proj-devel ». openSUSE éclate
#               PROJ en trois paquets : libproj25 la bibliothèque, proj-devel
#               les en-têtes, proj les outils en ligne de commande. pyproj ne
#               se contente pas des en-têtes — il EXÉCUTE « proj » pour
#               localiser l'installation, et sans lui s'arrête sur « proj
#               executable not found. Please set the PROJ_DIR variable ».
#               proj-devel ne le tire pas : la dépendance manque en silence
#               jusqu'au build, et aucune roue s390x ne vient l'éviter.
zyp_soft qpdf-devel libjpeg8-devel cmake pkgconf-pkg-config \
  tbb-devel geos-devel proj proj-devel krb5-devel ninja clang-devel \
  llvm-devel
# Tumbleweed livre qpdf 12.3.2 : l'appel ne fait que le constater. Il est là
# pour que les trois familles suivent la même règle.
el_qpdf_ensure
# pymupdf charge « libclang.so » par son nom nu, via ctypes ; le paquet ne
# livre qu'un nom versionné. Il ne manque que le lien — même correctif que
# côté apt et dnf.
for d in /usr/lib64 /usr/lib; do
  if [ -d "${d}" ] && [ ! -e "${d}/libclang.so" ]; then
    so="$(ls -1 "${d}"/libclang.so.* 2> /dev/null | sort -V | tail -1)"
    if [ -n "${so}" ]; then
      sudo ln -s "${so}" "${d}/libclang.so" && sudo ldconfig
      echo "libclang.so -> ${so}"
    fi
  fi
done
