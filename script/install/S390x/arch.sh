#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Fragment SOURCÉ par install_arch_linux.sh, sur s390x seulement : swap,
# bibliothèques système des roues qui compilent, qpdf, PROJ et Rust. Hérite
# de l'appelant PAC et les variables d'env_var.sh.
#
# Arch ne publie pas s390x : les paquets viennent du portage communautaire
# archlinux-s390x, et son dépôt ne porte que ce que ce portage a bâti. Un
# nom inconnu y fait échouer TOUTE la transaction pacman — il n'y a pas
# d'équivalent de --skip-unavailable — d'où le lot dur réduit à ce dont les
# roues ont réellement besoin, et la boucle best-effort pour le reste.

. ./script/install/S390x/lib_qpdf.sh
. ./script/install/S390x/lib_proj.sh
. ./script/install/S390x/lib_lowmem.sh
. ./script/install/S390x/lib_rust.sh

echo -e "\n---- Dependances de compilation s390x ----"
# La mémoire est la ressource qui manque en premier ici : cc1plus demande
# jusqu'à 2,5 Gio pour un seul fichier, et poetry en lance plusieurs de
# front. Le tueur du noyau abrège sans jamais nommer la mémoire (« Killed
# signal terminated program cc1plus »). On complète par du swap avant d'en
# arriver là.
el_swap_ensure

# Le lot DUR : chacun porte une roue qui, sans lui, arrête « poetry install ».
# Arch ne sépare pas les en-têtes dans un paquet « -devel » : un seul nom
# donne la bibliothèque et ses en-têtes.
#
# geos      shapely          proj      pyproj (exige PROJ >= 9.4)
# libtiff   pillow, et dépendance ferme de proj
# onetbb    manifold3d, dont le CMake s'arrête sur « Parallel mode enabled,
#           but tbb was not found »
# libsodium pynacl — voir plus bas, c'est le seul que la chaîne ne nommait
#           nulle part
# libcups   pycups, qu'Odoo importe dans odoo/addons/hw_drivers
# krb5      les extensions Kerberos ; libjpeg-turbo et zlib, pillow
${PAC} rust cmake ninja pkgconf krb5 libjpeg-turbo zlib \
  geos proj libtiff onetbb libsodium libcups qpdf
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "pacman s390x build dependencies installation error."
  exit 1
fi

# Best-effort : ce qui sert des modules Odoo optionnels. Paquet par paquet,
# pour la raison dite en tête — un nom absent du portage emporterait le lot.
for _pkg in geographiclib clang llvm swig gettext; do
  ${PAC} "${_pkg}" || echo "  ${_pkg} : non installé (optionnel), on continue."
done

# qpdf : pikepdf en exige 12.2.0. Le portage le bâtit depuis la recette
# d'Arch, qui suit l'amont ; el_qpdf_ensure vérifie le seuil et compile
# depuis les sources si la version livrée est en dessous.
el_qpdf_ensure
# PROJ : pyproj exige 9.4, et sa configuration EXÉCUTE le binaire « proj »
# pour localiser l'installation — les en-têtes seules ne suffisent pas. Le
# paquet d'Arch porte les deux.
el_proj_ensure
# Plusieurs roues portent une extension RUST et non C : bcrypt et
# cryptography en tête. Sur amd64 leurs roues masquent le besoin ; ici tout
# compile, et bcrypt s'arrête sur « error: can't find Rust compiler ».
if ! command -v cargo > /dev/null 2>&1; then
  echo "Attention : cargo absent, bcrypt et cryptography ne compileront pas."
fi
el_rust_ensure
