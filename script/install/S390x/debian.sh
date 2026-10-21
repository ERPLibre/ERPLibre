#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Fragment SOURCÉ par install_debian_dependency.sh (Debian, Ubuntu, Mint),
# sur s390x seulement : swap, paquets de compilation, libclang, qpdf, PROJ et
# Rust. Sur cette architecture PyPI ne publie presque aucune roue, et
# poetry install compile ce que pip poserait ailleurs tout prêt. Hérite de
# l'appelant APT_GET et les variables d'env_var.sh ; un « exit » y arrête
# toute l'installation, comme dans le script qui le source.

. ./script/install/S390x/lib_qpdf.sh
. ./script/install/S390x/lib_proj.sh
. ./script/install/S390x/lib_lowmem.sh
. ./script/install/S390x/lib_rust.sh

echo "Arch s390x detected"
# La mémoire est la ressource qui manque en premier ici : cc1plus demande
# jusqu'à 2,5 Gio pour un seul fichier de matplotlib, et le tueur du noyau
# abrège sans jamais nommer la mémoire (« Killed signal terminated program
# cc1plus »). On complète par du swap avant d'en arriver là.
el_swap_ensure
# Sur une VM fraîche, l'index apt peut être vide : « apt install » échouerait
# alors sur TOUT le lot, et l'absence d'un seul paquet ne se voit que bien
# plus loin, sous la forme d'une commande introuvable.
${APT_GET} update
# « ${APT_GET} » et non « sudo apt » : au 1er boot d'une image cloud,
# cloud-init tient le verrou apt, et un « apt install » nu échoue AUSSITÔT.
# Ces trois lots étaient les seuls du script à contourner le wrapper, et
# aucun ne vérifiait son résultat : libqpdf-dev manquait sans un mot, et
# l'échec ne se voyait qu'une heure plus tard, à la compilation de pikepdf.
# Un nom de paquet CHANGE d'une version d'Ubuntu à l'autre : GeographicLib
# s'appelle « libgeographic-dev » sur 20.04 et 22.04, « libgeographiclib-dev »
# depuis 24.04. Le nom récent existe pourtant dans la base apt des anciennes,
# SANS version installable — apt refuse alors le lot ENTIER, emportant les
# quatorze autres paquets. On demande donc à apt lui-même quel nom est
# réellement installable, seule autorité sur la question.
apt_pick() {
  for candidate in "$@"; do
    if apt-get install -s -qq "${candidate}" > /dev/null 2>&1; then
      echo "${candidate}"
      return 0
    fi
  done
  echo "$1"
}
# Vrai si dpkg considère le paquet installé et configuré.
apt_is_installed() {
  [ "$(dpkg-query -W -f='${db:Status-Status}' "$1" 2>/dev/null)" = "installed" ]
}
# Le lot d'abord, pour la vitesse. S'il échoue, on reprend paquet par paquet
# afin de NOMMER le fautif : sinon un seul nom obsolète masque les autres et
# le message ne dit pas lequel corriger.
apt_install_batch() {
  if ${APT_GET} install "$@" -y; then
    return 0
  fi
  # Un dépaquetage raté laisse dpkg à moitié configuré, et TOUT apt suivant
  # rend « Unmet dependencies » — y compris pour des paquets déjà installés.
  # Sans cette réparation, la boucle ci-dessous accusait les quinze paquets
  # à cause d'un seul, et l'installation s'arrêtait sur un paquet présent.
  echo "Lot apt en echec : tentative de reparation dpkg..."
  sudo dpkg --configure -a || true
  ${APT_GET} --fix-broken install -y || true
  if ${APT_GET} install "$@" -y; then
    echo "Reparation reussie."
    return 0
  fi
  echo "Reprise paquet par paquet pour identifier le fautif..."
  df -h / | sed 's/^/  disque: /'
  APT_FAILED=""
  for one in "$@"; do
    ${APT_GET} install "${one}" -y && continue
    # L'échec peut n'être qu'un contrecoup de l'état global : on ne l'impute
    # au paquet que si dpkg confirme qu'il n'est PAS installé.
    apt_is_installed "${one}" || APT_FAILED="${APT_FAILED} ${one}"
  done
  [ -z "${APT_FAILED}" ]
}
APT_FAILED=""
GEO_DEV="$(apt_pick libgeographiclib-dev libgeographic-dev)"
# manifold3d (via to-3mf) et pymupdf n'ont pas de roue s390x : ils se
# compilent, d'où tbb, cmake et ninja. Un seul lot, une seule reprise.
apt_install_batch rust-all libqpdf-dev libgeos-dev libproj-dev proj-bin \
  proj-data "${GEO_DEV}" freetds-dev freetds-bin libkrb5-dev libssl-dev \
  pkg-config build-essential zlib1g-dev libjpeg-dev libtbb-dev cmake \
    ninja-build libsqlite3-dev sqlite3 libtiff-dev libcurl4-openssl-dev
if [[ -n "${APT_FAILED}" ]]; then
  # Seul un paquet dont dépend la SUITE immédiate est bloquant. Les autres
  # servent des modules Odoo optionnels : les rendre fatals immobiliserait
  # toute l'installation pour un module que personne n'utilise ici.
  echo "Paquets s390x non installables :${APT_FAILED}"
  for essential in build-essential pkg-config libssl-dev zlib1g-dev \
    libjpeg-dev cmake; do
    case " ${APT_FAILED} " in
      *" ${essential} "*)
        echo "apt-get s390x : '${essential}' est indispensable, arret."
        exit 1
        ;;
    esac
  done
  echo "Aucun n'est indispensable a la compilation : on continue."
fi
# pymupdf non plus n'a pas de roue s390x : il compile MuPDF, dont le
# générateur de liaisons charge « libclang.so » par son nom nu, via ctypes.
# La roue PyPI libclang, qui embarque cette bibliothèque, n'existe pas ici.
# Le paquet de la distribution la fournit bien dans le chemin de l'éditeur de
# liens, mais sous un nom versionné : il ne manque que le lien non versionné.
${APT_GET} install libclang-dev -y
CLANG_LIB_DIR="/usr/lib/s390x-linux-gnu"
if [ ! -e "${CLANG_LIB_DIR}/libclang.so" ]; then
  CLANG_SO="$(ls -1 ${CLANG_LIB_DIR}/libclang-[0-9]*.so 2>/dev/null | sort -V | tail -1)"
  if [ -n "${CLANG_SO}" ]; then
    sudo ln -s "${CLANG_SO}" "${CLANG_LIB_DIR}/libclang.so"
    sudo ldconfig
    echo "libclang.so -> ${CLANG_SO}"
  else
    echo "Attention : libclang introuvable, la compilation de pymupdf va echouer."
  fi
fi
# pikepdf se lie a qpdf, dont il exige 12.2.0 au minimum. Ubuntu 24.04 en
# livre 11.9.0 ; 25.10 et 26.04 passent, d'ou le partage observe. Le detail
# -- seuil, version batie, chemin d'installation -- est dans S390x/lib_qpdf.sh,
# partage avec les scripts dnf et zypper qui butaient sur le meme mur.
el_qpdf_ensure
# pyproj exige PROJ 9.4 ; bookworm en livre 9.1.1. Meme mecanique que
# qpdf, et meme portee etroite : ailleurs pyproj pose une roue qui
# embarque sa propre PROJ, ici il compile contre celle du systeme.
el_proj_ensure
# cryptography et orjson ne publient aucune roue s390x : ils se compilent,
# et Ubuntu 26.04 livre un Rust sous leur seuil. Voir S390x/lib_rust.sh.
el_rust_ensure
