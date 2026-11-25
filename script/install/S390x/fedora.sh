#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Fragment SOURCÉ par install_fedora_dependency.sh (Fedora, AlmaLinux,
# Rocky), sur s390x seulement : swap, paquets de compilation, qpdf, Rust et
# libclang. Hérite de l'appelant DNF et les variables d'env_var.sh.

. ./script/install/S390x/lib_qpdf.sh
. ./script/install/S390x/lib_lowmem.sh
. ./script/install/S390x/lib_rust.sh

echo -e "\n---- Dependances de compilation s390x ----"
# La mémoire est la ressource qui manque en premier ici : cc1plus
# demande jusqu'à 2,5 Gio pour un seul fichier de matplotlib, et le
# tueur du noyau abrège sans jamais nommer la mémoire (« Killed signal
# terminated program cc1plus »). On complète par du swap avant d'en
# arriver là.
el_swap_ensure
# Best-effort : un nom qui change d'une version à l'autre ne doit pas
# emporter le lot. Ce qui est vraiment indispensable est déjà installé
# au-dessus (compilateurs) ou plus bas (pyenv, PostgreSQL).
# « rust » et « cargo » : plusieurs paquets Python portent une extension
# RUST, pas seulement C — bcrypt et cryptography en tête. Sur amd64 leurs
# roues masquent le besoin ; ici tout compile, et bcrypt s'arrête net sur
# « error: can't find Rust compiler ». La version livrée ne suffit pas
# toujours : AlmaLinux 10 donne 1.92, sous le seuil d'orjson, que
# el_rust_ensure complète plus bas.
# « proj » nommé À CÔTÉ de « proj-devel » : pyproj n'a pas de roue s390x, il
# compile, et sa configuration EXÉCUTE le binaire « proj » pour localiser
# l'installation — les en-têtes seules ne suffisent pas. Ici le paquet
# principal porte /usr/bin/proj et « proj-devel » l'exige, donc l'arriver
# transitivement fonctionnerait ; on le nomme quand même, comme apt le fait
# avec « proj-bin », parce que openSUSE a prouvé que cette arête n'existe pas
# partout — elle y manque, et l'échec n'apparaît qu'au build.
# « gcc-gfortran » et « openblas-devel » : scipy n'a pas de roue s390x, et sa
# compilation exige un compilateur Fortran et un BLAS/LAPACK. Sans Fortran,
# meson s'arrête sur « Unknown compiler(s) », et scikit-learn tombe avec lui,
# puisqu'il bâtit son propre scipy pour se compiler. openblas-devel ne livre
# aucun fichier pkg-config ici : meson trouve la bibliothèque par sa
# recherche système, sans réglage.
${DNF} \
  rust cargo \
  libjpeg-turbo-devel zlib-devel geos-devel proj proj-devel \
  krb5-devel tbb-devel ninja-build clang-devel llvm-devel \
  GeographicLib-devel pkgconf-pkg-config cmake gcc-gfortran openblas-devel

# Le Python des versions supportées, quand la distribution le livre :
# el_python_exec (lib_python_provider.sh) prend alors l'interpréteur du
# système au lieu de compiler CPython. Ici cette compilation est le seul
# autre chemin, et elle échoue dès que l'OpenSSL du système est plus récent
# que ce que le module _ssl de cette version sait lire : OpenSSL 4 rend
# opaques les types ASN1_* que CPython 3.12 manipule directement (« invalid
# use of incomplete typedef 'ASN1_OCTET_STRING' »). Le -devel porte Python.h,
# sans lequel aucune extension C du venv ne compile. Une version absente du
# dépôt est sautée, et un patch plus ancien que celui que conf/ exige est
# écarté par el_python_exec : pyenv reste alors le repli.
for py_minor in $(python3 -c '
import json
with open("conf/supported_version_erplibre.json") as f:
    data = json.load(f)
print(" ".join(sorted({
    ".".join(v["python_version"].split(".")[:2])
    for v in data.values() if not v.get("is_deprecated")
})))' 2> /dev/null); do
  if dnf repoquery -q --latest-limit 1 "python${py_minor}-devel" 2> /dev/null \
    | grep -q .; then
    ${DNF} "python${py_minor}" "python${py_minor}-devel"
  fi
done

# qpdf : pikepdf en exige ${EL_QPDF_MIN} (S390x/lib_qpdf.sh), que le paquet de
# la distribution ne donne pas toujours. EL9 livre 10.3 — même pas « qpdf/QPDFJob.hh », d'où trois
# cents lignes de g++ sans un mot sur qpdf ; EL10 livre 11.9.
#
# On ne pose donc « qpdf-devel » QUE s'il atteint le seuil, au lieu de le
# poser puis de le contourner : contrairement à Debian, l'éditeur de liens de
# RHEL cherche /usr/lib64 AVANT /usr/local/lib64. Le -devel trop ancien ferait
# lier pikepdf contre l'ancienne bibliothèque malgré les en-têtes neufs de
# /usr/local/include — une incohérence bien plus difficile à lire qu'un
# en-tête absent. Sans lui, el_qpdf_ensure fournit tout depuis les sources.
qpdf_repo="$(dnf repoquery --qf '%{version}' --latest-limit 1 qpdf-devel \
  2> /dev/null | tail -1)"
if el_qpdf_ge_min "${qpdf_repo}"; then
  ${DNF} qpdf-devel
else
  echo "qpdf-devel ${qpdf_repo:-absent} sous le seuil de pikepdf : compilation depuis les sources."
fi
el_qpdf_ensure
# Le dire ICI plutôt que de laisser bcrypt le découvrir une heure plus tard.
if ! command -v cargo > /dev/null 2>&1; then
  echo "Attention : cargo absent, bcrypt et cryptography ne compileront pas."
fi
el_rust_ensure
# pymupdf charge « libclang.so » par son nom nu, via ctypes. Le paquet le
# livre sous un nom versionné : il ne manque que le lien.
for d in /usr/lib64 /usr/lib; do
  if [ -d "${d}" ] && [ ! -e "${d}/libclang.so" ]; then
    so="$(ls -1 "${d}"/libclang.so.* 2> /dev/null | sort -V | tail -1)"
    if [ -n "${so}" ]; then
      sudo ln -s "${so}" "${d}/libclang.so" && sudo ldconfig
      echo "libclang.so -> ${so}"
    fi
  fi
done
