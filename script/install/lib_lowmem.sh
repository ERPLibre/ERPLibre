#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque SOURÇABLE : compiler sans se faire tuer par manque de mémoire.
#
# Le symptôme est toujours le même, et il ne nomme jamais la mémoire :
#   c++: fatal error: Killed signal terminated program cc1plus
# « Killed » est un SIGKILL, donc le tueur de mémoire du noyau. Il est arrivé
# sur matplotlib, dont _backend_agg_wrapper.cpp instancie assez de gabarits
# C++ pour demander 1,5 à 2,5 Gio à cc1plus — À LUI SEUL.
#
# Deux causes se cumulent, et il faut les traiter toutes les deux :
#   1. la VM est petite (le catalogue démarre à 1 ou 2 Gio) ;
#   2. le moteur de build lance nproc compilations EN PARALLÈLE, chacune avec
#      son propre cc1plus. Six cœurs suffisent à épuiser 8 Gio.
#
# Réservé aux architectures sans roue PyPI par l'appelant : ailleurs pip pose
# des binaires et rien de tout cela ne s'exécute.

# RAM + swap visés, en Gio. « 0 » désactive entièrement la création de swap,
# pour qui préfère dimensionner sa machine lui-même.
EL_SWAP_TARGET_GIB="${EL_SWAP_TARGET_GIB:-8}"
EL_SWAP_FILE="${EL_SWAP_FILE:-/swapfile.erplibre}"
# Mio de mémoire à réserver par compilation simultanée. 2048 vient du pic
# mesuré de cc1plus sur matplotlib ; en dessous, le tueur revient.
EL_MEM_PER_JOB_MB="${EL_MEM_PER_JOB_MB:-2048}"

el_mem_mb() {
  awk '/^MemTotal:/ {print int($2 / 1024)}' /proc/meminfo 2> /dev/null || echo 0
}

el_swap_mb() {
  awk '/^SwapTotal:/ {print int($2 / 1024)}' /proc/meminfo 2> /dev/null || echo 0
}

# Complète la mémoire par un fichier d'échange, si elle manque.
#
# Volontairement NON persisté dans /etc/fstab : un swap déclaré et disparu
# dégrade le démarrage, et cette machine n'en a besoin que le temps de
# l'installation. La fonction est idempotente, elle repassera au besoin.
el_swap_ensure() {
  local ram swap missing free_mb size
  [ "${EL_SWAP_TARGET_GIB}" -gt 0 ] 2> /dev/null || return 0
  ram="$(el_mem_mb)"
  swap="$(el_swap_mb)"
  missing=$((EL_SWAP_TARGET_GIB * 1024 - ram - swap))
  if [ "${missing}" -le 0 ]; then
    echo "  memoire : ${ram} Mio + ${swap} Mio de swap, suffisant."
    return 0
  fi
  if [ -e "${EL_SWAP_FILE}" ]; then
    # Déjà là mais pas actif : un « swapon » suffit, on ne le réécrit pas.
    sudo swapon "${EL_SWAP_FILE}" 2> /dev/null && {
      echo "  swap : ${EL_SWAP_FILE} reactive."
      return 0
    }
  fi
  # Ne jamais remplir le disque pour gagner de la mémoire : au plus la moitié
  # de ce qui reste libre. Un disque plein casse l'installation autrement.
  free_mb="$(df -Pm / | awk 'NR==2 {print $4}')"
  size="${missing}"
  [ "${size}" -gt $((free_mb / 2)) ] && size=$((free_mb / 2))
  if [ "${size}" -lt 512 ]; then
    echo "  swap : pas assez d'espace disque libre (${free_mb} Mio), abandon." >&2
    return 0
  fi
  echo "  memoire : ${ram} Mio seulement — ajout de ${size} Mio de swap."
  # fallocate est instantané ; dd est le repli des systèmes de fichiers qui
  # ne le supportent pas (et un swap sur trous ne fonctionnerait pas).
  if ! sudo fallocate -l "${size}M" "${EL_SWAP_FILE}" 2> /dev/null; then
    sudo dd if=/dev/zero of="${EL_SWAP_FILE}" bs=1M count="${size}" \
      status=none 2> /dev/null || {
      echo "  swap : creation impossible, on continue sans." >&2
      return 0
    }
  fi
  sudo chmod 600 "${EL_SWAP_FILE}"
  if sudo mkswap "${EL_SWAP_FILE}" > /dev/null 2>&1 \
    && sudo swapon "${EL_SWAP_FILE}"; then
    echo "  swap : ${size} Mio actifs (${EL_SWAP_FILE})."
  else
    echo "  swap : activation impossible, on continue sans." >&2
    sudo rm -f "${EL_SWAP_FILE}"
  fi
}

# Nombre de compilations simultanées que la mémoire tolère.
el_build_jobs() {
  local total cpus jobs
  total=$(($(el_mem_mb) + $(el_swap_mb)))
  cpus="$(nproc 2> /dev/null || echo 1)"
  jobs=$((total / EL_MEM_PER_JOB_MB))
  [ "${jobs}" -lt 1 ] && jobs=1
  [ "${jobs}" -gt "${cpus}" ] && jobs="${cpus}"
  echo "${jobs}"
}

# Exporte de quoi brider les moteurs de build. À appeler AVANT « poetry
# install », dans le shell qui le lance.
#
#   make   MAKEFLAGS, lu par tout Makefile.
#   cmake  CMAKE_BUILD_PARALLEL_LEVEL, lu par « cmake --build » (manifold3d).
#   ninja  aucune variable de parallélisme n'existe — mais meson-python lit
#          « NINJA », le CHEMIN de l'exécutable (vérifié dans mesonpy 0.20 :
#          « env_ninja = os.environ.get('NINJA') »). On y met une enveloppe
#          qui ajoute le -j. C'est ce qui sauve matplotlib.
#   MAX_JOBS  convention de PyTorch et de quelques autres.
el_build_limit_jobs() {
  local jobs real wrapper
  jobs="$(el_build_jobs)"
  export MAKEFLAGS="-j${jobs}"
  export CMAKE_BUILD_PARALLEL_LEVEL="${jobs}"
  export MAX_JOBS="${jobs}"
  real="$(command -v ninja || command -v ninja-build || true)"
  if [ -n "${real}" ]; then
    wrapper="${TMPDIR:-/tmp}/el-ninja-j${jobs}"
    printf '#!/bin/sh\nexec %s -j%s "$@"\n' "${real}" "${jobs}" > "${wrapper}"
    chmod +x "${wrapper}"
    export NINJA="${wrapper}"
  fi
  echo "  compilation bridee a ${jobs} tache(s) simultanee(s)."
}
