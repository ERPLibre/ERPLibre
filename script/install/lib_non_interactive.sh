#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque SOURCÉE depuis la racine d'ERPLibre par les scripts
# d'installation : le mode non interactif, où personne n'est au clavier.
#
# EL_NON_INTERACTIVE=1 l'active ; « ./todo.sh install --non-interactive » et
# « make install_non_interactive » la posent pour tous les processus enfants.
# Hors de ce mode, rien ici ne change le comportement : une question posée
# à quelqu'un qui est là reste posée.
#
# Dans ce mode :
# - une question délibérée prend la réponse fournie, ou fait échouer
#   l'installation en nommant la variable qui manque — chaque script le fait
#   à l'endroit de sa question ;
# - les questions qu'un outil pose de lui-même, et qui ne sont pas des choix
#   (debconf, needrestart, un fichier de configuration modifié, un mot de
#   passe git ou pip), reçoivent la réponse qui ne change rien d'existant :
#   el_non_interactive_env exporte ce qu'il faut ;
# - sudo ne peut pas demander de mot de passe : el_sudo_preflight le vérifie
#   au départ plutôt qu'au milieu de l'installation.

# Rend 0 en mode non interactif, 1 sinon.
el_non_interactive() {
  [ "${EL_NON_INTERACTIVE:-}" = "1" ]
}

# En mode non interactif, exporte les variables qui coupent les questions des
# outils lancés sans sudo. sudo vide l'environnement : les commandes lancées
# par sudo reçoivent les leurs sur leur propre ligne, voir el_apt_get.
# NEEDRESTART_MODE=l liste les services à relancer sans en relancer aucun.
el_non_interactive_env() {
  el_non_interactive || return 0
  export DEBIAN_FRONTEND=noninteractive
  export NEEDRESTART_MODE=l
  export GIT_TERMINAL_PROMPT=0
  export PIP_NO_INPUT=1
}

# Rend sur stdout la commande apt-get à employer, sudo compris. Le verrou apt
# est attendu jusqu'à 10 min : sur une image cloud fraîche, cloud-init ou
# unattended-upgrades le tiennent souvent au premier démarrage. En mode non
# interactif, debconf ne pose aucune question, needrestart se contente de
# lister, et un fichier de configuration modifié localement est gardé.
el_apt_get() {
  if el_non_interactive; then
    printf '%s' "sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l" \
      " apt-get -o DPkg::Lock::Timeout=600" \
      " -o Dpkg::Options::=--force-confdef" \
      " -o Dpkg::Options::=--force-confold"
  else
    printf '%s' "sudo apt-get -o DPkg::Lock::Timeout=600"
  fi
}

# En mode non interactif, rend 1 avec la marche à suivre si sudo demanderait
# un mot de passe ; rend 0 sinon, ou pour root. Hors de ce mode, rend 0 sans
# rien vérifier : sudo pourra demander son mot de passe.
el_sudo_preflight() {
  el_non_interactive || return 0
  [ "$(id -u)" = "0" ] && return 0
  sudo -n true 2> /dev/null && return 0
  echo "Mode non interactif : sudo demande un mot de passe, et personne ne"
  echo "  peut le saisir. Ouvrez un ticket sudo juste avant (sudo -v), ou"
  echo "  donnez à ce compte un sudo sans mot de passe (NOPASSWD)."
  return 1
}

# En mode non interactif, garde vivant le ticket sudo tant que le script
# appelant tourne : un ticket ouvert par « sudo -v » expire au bout de
# timestamp_timeout (15 min par défaut), et une compilation plus longue
# ferait demander un mot de passe au sudo suivant. « sudo -n -v » le
# rafraîchit chaque minute, dans un processus en arrière-plan qui s'arrête
# avec l'appelant, ou dès que sudo refuse. Sans effet hors de ce mode et
# pour root.
el_sudo_keepalive() {
  el_non_interactive || return 0
  [ "$(id -u)" = "0" ] && return 0
  local parent="$$"
  (
    while kill -0 "${parent}" 2> /dev/null; do
      sudo -n -v 2> /dev/null || exit 0
      sleep 60
    done
  ) > /dev/null 2>&1 &
}
