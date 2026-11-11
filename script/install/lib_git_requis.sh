#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque SOURCÉE depuis la racine d'ERPLibre : git avant TODO.
#
# TODO importe GitPython, qui refuse de se charger sans exécutable git :
# sans lui, « ./todo.sh » s'arrête sur un traceback avant d'offrir quoi que
# ce soit, et l'étape système qui poserait git ne peut plus être lancée.
# el_git_requis pose donc git d'abord, par le gestionnaire de paquets du
# système.

. ./script/install/lib_non_interactive.sh

# Rend 0 quand quelqu'un peut répondre au terminal ; les tests la remplacent.
el_git_peut_demander() {
  [ -t 0 ] && [ -t 2 ]
}

# Rend sur stdout la commande qui pose git sur ce système, sudo compris, ou
# rien quand aucun gestionnaire connu n'est là. En mode non interactif, sudo
# reçoit -n : il échoue au lieu de demander un mot de passe que personne ne
# saisirait. Pour root, sudo est retiré : un conteneur minimal n'en a pas.
el_git_commande() {
  local cmd=""
  if command -v apt-get > /dev/null 2>&1; then
    local apt
    apt="$(el_apt_get)"
    cmd="${apt} update && ${apt} install -y git"
  elif command -v dnf > /dev/null 2>&1; then
    cmd="sudo dnf install -y git"
  elif command -v pacman > /dev/null 2>&1; then
    cmd="sudo pacman -S --needed --noconfirm git"
  elif command -v zypper > /dev/null 2>&1; then
    cmd="sudo zypper --non-interactive install git"
  elif command -v brew > /dev/null 2>&1; then
    cmd="brew install git"
  fi
  [ -n "${cmd}" ] || return 1
  if [ "$(id -u)" = "0" ]; then
    cmd="${cmd//sudo /}"
  elif el_non_interactive; then
    cmd="${cmd//sudo /sudo -n }"
  fi
  printf '%s\n' "${cmd}"
}

# Rend 0 quand git est là, ou vient d'être posé. Sinon, dit pourquoi et
# comment le poser, et rend 1. Devant un terminal, la question vaut oui par
# défaut ; en mode non interactif, git est posé sans question : c'est un
# prérequis de l'installation demandée. Sans terminal hors de ce mode, rien
# n'est lancé : la commande est donnée à copier.
el_git_requis() {
  local cmd reponse
  command -v git > /dev/null 2>&1 && return 0
  echo "git est absent : TODO et l'installation d'ERPLibre en ont besoin." >&2
  if ! cmd="$(el_git_commande)"; then
    if [ -e /etc/NIXOS ]; then
      echo "  Sur NixOS : ajoutez git a environment.systemPackages, ou" >&2
      echo "  nix-env -iA nixos.git, puis relancez." >&2
    else
      echo "  Aucun gestionnaire de paquets connu : posez git, puis" >&2
      echo "  relancez." >&2
    fi
    return 1
  fi
  echo "  Commande : ${cmd}" >&2
  if ! el_non_interactive; then
    if ! el_git_peut_demander; then
      echo "  Lancez-la, puis relancez." >&2
      return 1
    fi
    printf "L'installer maintenant ? [O/n] " >&2
    read -r reponse || reponse=""
    case "${reponse}" in
      n | N | non | Non | NON | no | No | NO)
        echo "git n'est pas pose : TODO ne demarre pas." >&2
        return 1
        ;;
    esac
  fi
  bash -c "${cmd}"
  hash -r
  if ! command -v git > /dev/null 2>&1; then
    echo "git n'a pas pu etre pose : TODO ne demarre pas." >&2
    return 1
  fi
  echo "git est pose : $(git --version)" >&2
}
