#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque SOURCÉE par install_dev.sh (make install_os) et
# install_erplibre.sh (make install), avant toute installation.
#
# el_arch_check : rend 0 sur une architecture supportée — amd64, arm64,
# s390x. Sur une autre, il le dit, puis demande s'il faut continuer : sur
# une telle architecture, PyPI n'a pas de wheel pour une bonne part des
# dépendances, pip les compile, et rien n'y est testé. La réponse se donne
# en français ou en anglais (o, oui, y, yes, toute casse) ; Entrée seule
# vaut non, et rend 1. Sans terminal sur l'entrée, personne ne peut
# répondre : la réponse est non, sauf si EL_ALLOW_UNSUPPORTED_ARCH=1 est
# dans l'environnement, qui répond oui sans question.

el_arch_check() {
  local arch reponse
  arch="$(uname -m)"
  case "${arch}" in
    x86_64 | amd64 | aarch64 | arm64 | s390x) return 0 ;;
  esac
  echo "Architecture ${arch} non supportée : ERPLibre supporte amd64"
  echo "  (x86_64), arm64 (aarch64) et s390x. Ailleurs, pip compile une"
  echo "  bonne part des dépendances, et rien n'y est testé."
  if [[ "${EL_ALLOW_UNSUPPORTED_ARCH:-}" == "1" ]]; then
    echo "  EL_ALLOW_UNSUPPORTED_ARCH=1 : l'installation continue."
    return 0
  fi
  if [[ ! -t 0 ]]; then
    echo "  Aucun terminal pour répondre : arrêt. Pour continuer sans"
    echo "  question, préfixez la commande :"
    echo "    EL_ALLOW_UNSUPPORTED_ARCH=1 make install_os"
    echo "    EL_ALLOW_UNSUPPORTED_ARCH=1 make install"
    return 1
  fi
  printf '  Continuer quand même, à vos risques ? [o/N] '
  read -r reponse || return 1
  case "$(printf '%s' "${reponse}" | tr '[:upper:]' '[:lower:]')" in
    o | oui | y | yes) return 0 ;;
  esac
  echo "  Arrêt. EL_ALLOW_UNSUPPORTED_ARCH=1 devant la commande répond oui"
  echo "  sans question : EL_ALLOW_UNSUPPORTED_ARCH=1 make install"
  return 1
}
