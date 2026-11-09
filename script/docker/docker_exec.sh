#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Ouvre un shell bash en root dans le conteneur ERPLibre du projet docker
# compose du répertoire courant.
#
# Le shell ne garde que SETUID et SETGID, quel que soit le cap_add du
# compose : capsh retire les autres de ses capacités permises et effectives,
# ce qui ne demande aucune capacité, pose no-new-privileges et lance bash. Un
# execve sous root rendrait l'ensemble limitant (bounding) ; no-new-privileges
# le borne aux capacités permises d'avant, et le retrait de l'ensemble
# limitant, qui exigerait CAP_SETPCAP, n'est pas nécessaire. Sans CHOWN,
# DAC_OVERRIDE ni FOWNER, root n'y lit ni n'écrit ce que les permissions lui
# refusent, et apt n'y installe rien, même quand le compose donne le cap_add
# plus long d'APT_EXTRA_PACKAGES : un paquet Debian s'ajoute par cette liste,
# que l'entrypoint installe à chaque démarrage. capsh vient du paquet
# libcap2-bin, que les Dockerfile installent ; sans lui, aucun shell root
# ne s'ouvre.
#
# Le shell ne lit rien que odoo puisse réécrire : il démarre dans « / », sous
# env -i avec un PATH réduit aux répertoires système, et bash ne lit ni profil
# ni bashrc. Un Odoo compromis ne place donc rien sur le chemin du root qui
# l'ouvre.
#
# Le shell du compte odoo, celui qui possède /ERPLibre et les venvs, s'ouvre
# depuis le répertoire du compose par :
#   docker compose exec -u odoo ERPLibre bash

set -euo pipefail

source "$(dirname "$0")/lib_conteneur.sh"
conteneur=$(conteneur_erplibre)

# sh, lancé par env -i, cherche capsh dans le PATH système et s'arrête sans
# shell root s'il manque ; sinon exec le remplace par capsh, puis bash. Le
# script de sh tient sur une ligne.
DEMARRER='command -v capsh >/dev/null || { echo "capsh is missing: add'
DEMARRER+=' libcap2-bin to APT_EXTRA_PACKAGES; the root shell does not open'
DEMARRER+=' without it." >&2; exit 1; }; exec capsh --no-new-privs --noamb'
DEMARRER+=' --caps=cap_setuid,cap_setgid=ep --shell=/bin/bash --'
DEMARRER+=' --noprofile --norc'

exec docker exec -u root -w / -ti "${conteneur}" \
  /usr/bin/env -i HOME=/root TERM=xterm LANG=C.UTF-8 \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  PS1='\u@\h:\w\$ ' \
  sh -c "${DEMARRER}"
