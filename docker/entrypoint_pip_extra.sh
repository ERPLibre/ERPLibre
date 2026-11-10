#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Point d'entrée d'un conteneur ERPLibre qui installe des dépendances Python
# en plus de celles de l'image, puis passe la main à /entrypoint.sh.
#
# Deux listes, une par venv de l'image :
#   PIP_EXTRA_REQUIREMENTS_ODOO      venv d'Odoo (.venv.<.erplibre-version>),
#                                    celui qu'importent les addons
#   PIP_EXTRA_REQUIREMENTS_ERPLIBRE  venv des outils ERPLibre (.venv.erplibre),
#                                    celui des scripts de script/
# Chacune porte une exigence pip par mot : « humanize pyotp==2.9.0
# phonenumbers>=8.13,<9 ». Une contrainte de version ne contient ni espace ni
# guillemet : la valeur se coupe aux espaces et aux retours à la ligne, ceux
# d'un bloc YAML sur plusieurs lignes compris, et rien d'autre ne
# l'interprète. Vide ou absente, rien ne s'installe dans ce venv.
#
# Chaque pip résout sa liste contre ce que son venv porte déjà, et une
# exigence satisfaite ne télécharge rien. Une installation refusée arrête le
# conteneur avant Odoo, plutôt que de laisser un addon ou un script échouer à
# l'import ; la liste d'ERPLibre passe d'abord.
#
# Les venvs appartiennent au propriétaire du code de l'image, « odoo » ou
# « root » selon ERPLIBRE_CODE_OWNER à la construction. Lancé en root
# (« user: root » du compose), le script fait tourner chaque pip sous le
# propriétaire de son venv : un fichier posé par root dans un venv d'odoo
# bloquerait la réinstallation des dépendances qui suit un tirage. Il
# s'exécute ensuite sous le compte odoo par setpriv ; après l'exec, aucun
# processus du conteneur ne tourne plus en root. Lancé sous un autre compte,
# il installe s'il le peut et garde ce compte. USER reste intact :
# l'entrypoint de l'image y lit l'utilisateur PostgreSQL.
#
# Le venv d'Odoo se nomme d'après .erplibre-version, un fichier du code
# qu'Odoo peut réécrire. Le script n'en accepte qu'un nom de la forme
# « odoo18.0_python3.12.16 », et chaque venv doit se résoudre, liens suivis,
# en « .venv.<nom> » même, enfant direct du préfixe résolu : ni « .. » ni
# lien ne mène pip hors du préfixe. Python exécute à son lancement ce que
# porte son venv (pyvenv.cfg, les .pth de site-packages, l'interpréteur
# lui-même), puis la bibliothèque standard de l'interpréteur de base que
# nomme sa clé « home » (os.py, site.py, sitecustomize.py) : root ne lance
# donc pip dans un venv de root que si le venv, tout son contenu, la cible
# résolue de chacun de ses liens, ce dossier « home », le « lib » de son
# préfixe avec chaque lib/python*, et chaque dossier parent jusqu'à /
# appartiennent à root sans écriture pour le groupe ni pour les autres.
# Sinon, un autre compte pourrait substituer ce que root exécute, et le
# script s'arrête avant Odoo ; un préfixe qu'un autre compte possède ou
# peut écrire refuse ainsi tout pip en root.
# « python -I » retire du chemin d'import le dossier courant et les
# variables PYTHON*.
#
# L'installation vit dans la couche du conteneur : un redémarrage la garde,
# une recréation la refait au démarrage suivant.
#
# APT_EXTRA_PACKAGES porte des paquets Debian, un nom par mot, coupé comme
# les listes pip : les bibliothèques système qu'un paquet pip charge
# (« libmagic1 » pour python-magic), ou un navigateur pour Selenium. apt les
# installe en root, avant les listes pip, et avant que le script ne cède la
# main à odoo : root ne reçoit que des noms, validés, jamais une commande ni
# un fichier du code, qu'Odoo peut réécrire. Un nom déjà installé, ou fourni
# par un paquet installé (Provides), ne déclenche rien, ni réseau ni apt-get
# update.
#
# apt-get install lit un mot autrement que comme un nom dans trois cas : un
# « - » final retire le paquet, un « + » final est une action, et un nom
# qu'aucun paquet ne porte devient une expression régulière (« . » y est un
# joker). Il installe alors autre chose que le nom demandé, ou rien, et le
# nom reste absent de dpkg : chaque démarrage relance apt, et sans réseau,
# avec « restart: always », le conteneur redémarre en boucle. Le script
# refuse donc, avant apt-get install, un nom qui finit par « - » ou par un
# seul « + » (« g++ » passe), puis, après apt-get update, un nom que l'index
# d'apt ne connaît pas tel quel ; après l'installation, il vérifie que
# chaque nom est installé ou fourni.
#
# apt demande à root CHOWN, DAC_OVERRIDE, FOWNER et FSETID en plus de
# SETUID et SETGID. Sans CHOWN, DAC_OVERRIDE ou FOWNER, apt échoue ; sans
# FSETID, il réussit, mais un binaire setgid perd son bit, sans erreur. Le
# script les vérifie donc toutes avant apt, et s'arrête si l'une manque.
# setpriv les retire au passage à odoo, et no-new-privileges empêche Odoo
# de les regagner.

set -euo pipefail

prefixe="${ODOO_PREFIX:-/ERPLibre}"
compte="${ERPLIBRE_RUN_AS:-odoo}"
suite="${ERPLIBRE_ENTRYPOINT:-/entrypoint.sh}"
# Les tests le pointent sur un faux fichier d'état de processus.
etat_processus="${ERPLIBRE_PROC_STATUS:-/proc/self/status}"

# Masque des capacités qu'apt exige en plus de SETUID et SETGID :
# CHOWN (bit 0), DAC_OVERRIDE (1), FOWNER (3), FSETID (4).
CAPS_APT=$(((1 << 0) | (1 << 1) | (1 << 3) | (1 << 4)))

# deja_installe PAQUET : vrai si PAQUET est installé, ou fourni par un
# paquet installé — « libmagic1 » l'est par « libmagic1t64 » sous trixie.
deja_installe() {
  dpkg-query -W -f='${db:Status-Abbrev} ${Package} ${Provides}\n' \
    2>/dev/null | awk -v p="$1" '
      $1 == "ii" {
        for (i = 2; i <= NF; i++) { n = $i; sub(/[(,].*/, "", n); if (n == p) t = 1 }
      }
      END { exit !t }'
}

# connu_d_apt PAQUET : vrai si l'index d'apt porte le nom PAQUET tel quel,
# paquet réel ou virtuel. « pkgnames » compare un préfixe, sans expression
# régulière ; awk lit toute la sortie, donc aucun SIGPIPE ne fait échouer
# apt-cache sous pipefail. Un nom virtuel sans fournisseur passe : apt-get
# install le refuse ensuite avec une erreur.
connu_d_apt() {
  apt-cache --all-names pkgnames "$1" |
    awk -v p="$1" '$0 == p { t = 1 } END { exit !t }'
}

# vider_cache_apt : retire de la couche du conteneur les .deb téléchargés et
# les listes d'apt-get update, après une installation réussie. C'est du
# ménage : un échec avertit, et Odoo démarre quand même. Un refus avant
# l'installation garde les listes : sous « restart: always », chaque
# redémarrage ne refait alors qu'un apt-get update conditionnel, sans
# retélécharger l'index.
vider_cache_apt() {
  local sortie listes=""
  if ! { apt-get clean &&
    sortie=$(apt-config shell listes Dir::State::lists/d) &&
    eval "${sortie}" &&
    if [[ -n "${listes}" && -d "${listes}" ]]; then
      find "${listes}" -mindepth 1 -delete
    fi; }; then
    echo "Avertissement : le cache d'apt reste dans la couche du conteneur." >&2
  fi
}

# installer_apt : installe APT_EXTRA_PACKAGES en root ; sort en 1, Odoo non
# lancé, sur un nom invalide ou inconnu d'apt, sans root ou sans les
# capacités d'apt, si apt refuse, ou si un nom reste absent après apt.
installer_apt() {
  local paquets=() manquants=() p capeff
  read -r -d '' -a paquets <<<"${APT_EXTRA_PACKAGES:-}" || true
  ((${#paquets[@]})) || return 0
  for p in "${paquets[@]}"; do
    # Un nom Debian : ni option (« -o … »), ni version, ni chemin, ni
    # suffixe d'action d'apt — « - » final, ou « + » final seul.
    if [[ ! "${p}" =~ ^[a-z0-9][a-z0-9+.-]*([a-z0-9]|\+\+)$ ]]; then
      echo "Erreur : « ${p} » n'est pas un nom de paquet Debian (APT_EXTRA_PACKAGES) ; Odoo ne démarre pas." >&2
      exit 1
    fi
    deja_installe "${p}" || manquants+=("${p}")
  done
  if ! ((${#manquants[@]})); then
    echo "apt extra : déjà installés (${paquets[*]})"
    return 0
  fi
  if [[ "$(id -u)" != 0 ]]; then
    echo "Erreur : APT_EXTRA_PACKAGES s'installe en root (« user: root » du compose) ; Odoo ne démarre pas." >&2
    exit 1
  fi
  capeff=$(awk '/^CapEff:/ { print $2 }' "${etat_processus}")
  if (((16#${capeff:-0} & CAPS_APT) != CAPS_APT)); then
    echo "Erreur : APT_EXTRA_PACKAGES demande au compose « cap_add: [SETUID, SETGID, CHOWN, DAC_OVERRIDE, FOWNER, FSETID] » ; Odoo ne démarre pas." >&2
    exit 1
  fi
  echo "apt extra : ${manquants[*]}"
  if ! apt-get update -q; then
    echo "Erreur : apt n'a pas installé APT_EXTRA_PACKAGES ; Odoo ne démarre pas." >&2
    exit 1
  fi
  for p in "${manquants[@]}"; do
    if ! connu_d_apt "${p}"; then
      echo "Erreur : apt ne connaît aucun paquet « ${p} » (APT_EXTRA_PACKAGES) ; Odoo ne démarre pas." >&2
      exit 1
    fi
  done
  if ! DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    --no-install-recommends "${manquants[@]}"; then
    echo "Erreur : apt n'a pas installé APT_EXTRA_PACKAGES ; Odoo ne démarre pas." >&2
    exit 1
  fi
  vider_cache_apt
  for p in "${manquants[@]}"; do
    if ! deja_installe "${p}"; then
      echo "Erreur : apt a fini sans installer « ${p} » (APT_EXTRA_PACKAGES) ; Odoo ne démarre pas." >&2
      exit 1
    fi
  done
}

# chemin_sur CHEMIN : vrai si CHEMIN, déjà résolu, et chacun de ses parents
# jusqu'à / appartiennent à root sans écriture pour le groupe ni pour les
# autres : aucun autre compte ne peut y remplacer une entrée.
chemin_sur() {
  local c="$1" s
  while :; do
    s=$(stat -c '%u %a' -- "${c}") || return 1
    [[ "${s% *}" == 0 ]] && (((8#${s#* } & 8#022) == 0)) || return 1
    [[ "${c}" == / ]] && return 0
    c=$(dirname -- "${c}")
  done
}

# arbre_sur RACINE [OPTION_FIND…] : vrai si RACINE, déjà résolue, et tout ce
# qu'elle contient appartiennent à root sans écriture pour le groupe ni pour
# les autres, et si la cible résolue de chacun de ses liens passe chemin_sur.
# find ne suit pas les liens : un lien vers un dossier hors de RACINE est
# refusé, son contenu n'étant pas parcouru (« lib64 -> lib » d'un venv
# reste dedans). Un lien qui ne se résout pas compte comme une prise : sa
# cible peut encore être créée. Les options, « -maxdepth 1 » par exemple,
# bornent les deux parcours. Les parents de RACINE ne sont pas vérifiés.
arbre_sur() {
  local racine="$1" trouve lien cible
  shift
  trouve=$(find "${racine}" "$@" ! -type l \( ! -user 0 -o -perm /022 \) \
    -print -quit) || return 1
  [[ -z "${trouve}" ]] || return 1
  while IFS= read -r -d '' lien; do
    cible=$(realpath -e -- "${lien}") && chemin_sur "${cible}" || return 1
    if [[ -d "${cible}" && "${cible}" != "${racine}" &&
      "${cible}" != "${racine%/}/"* ]]; then
      return 1
    fi
  done < <(find "${racine}" "$@" -type l -print0)
}

# base_sure_pour_root VENV : vrai si l'interpréteur de base que nomme la clé
# « home » de pyvenv.cfg ne charge rien qu'un autre compte puisse réécrire.
# Python lit bin/pyvenv.cfg, sinon pyvenv.cfg, prend la première clé
# « home » et cherche sa bibliothèque standard en remontant de ce dossier :
# le premier parent qui porte lib/pythonX.Y/os.py devient le préfixe, d'où
# il charge os.py, site.py et sitecustomize.py, même sous -I. Le script
# n'accepte qu'un « home » déjà résolu, dont il vérifie le chemin jusqu'à /,
# et exige que le premier « lib » rencontré en remontant soit celui de
# Python, avec os.py et lib-dynload ; il vérifie ensuite ce « lib », ses
# entrées directes (libpython, pythonXY.zip) et l'arbre entier de chaque
# lib/python*. pyvenv.cfg appartient déjà à root, vérifié par
# venv_sur_pour_root.
base_sure_pour_root() {
  local venv="$1" cfg home d lib
  cfg="${venv}/bin/pyvenv.cfg"
  [[ -e "${cfg}" || -L "${cfg}" ]] || cfg="${venv}/pyvenv.cfg"
  home=$(awk '
    {
      i = index($0, "="); if (!i) next
      k = substr($0, 1, i - 1); gsub(/^[ \t\r\f\v]+|[ \t\r\f\v]+$/, "", k)
      if (tolower(k) != "home") next
      v = substr($0, i + 1); gsub(/^[ \t\r\f\v]+|[ \t\r\f\v]+$/, "", v)
      print v; exit
    }' "${cfg}") || return 1
  [[ -n "${home}" && "$(realpath -e -- "${home}")" == "${home}" ]] || return 1
  chemin_sur "${home}" || return 1
  d="${home}"
  until [[ -e "${d%/}/lib" || -L "${d%/}/lib" ]]; do
    [[ "${d}" != / ]] || return 1
    d=$(dirname -- "${d}")
  done
  lib=$(realpath -e -- "${d%/}/lib") && chemin_sur "${lib}" || return 1
  compgen -G "${lib}/python*/os.py" >/dev/null ||
    compgen -G "${lib}/python*/os.pyc" >/dev/null || return 1
  compgen -G "${lib}/python*/lib-dynload" >/dev/null || return 1
  arbre_sur "${lib}" -maxdepth 1 || return 1
  for d in "${lib}"/python*; do
    d=$(realpath -e -- "${d}") && chemin_sur "${d}" && arbre_sur "${d}" ||
      return 1
  done
}

# venv_sur_pour_root VENV : vrai si root peut lancer le python de VENV, déjà
# résolu, sans exécuter rien qu'un autre compte puisse réécrire : ni dans le
# venv, ni dans l'interpréteur de base qu'il désigne.
venv_sur_pour_root() {
  chemin_sur "$1" && arbre_sur "$1" && base_sure_pour_root "$1"
}

# lire_version VARIABLE : écrit dans « version » le nom du venv d'Odoo que
# porte .erplibre-version ; sort en 1, Odoo non lancé, si le fichier n'est
# pas un fichier ordinaire ou ne porte pas un tel nom. Le fichier est lu une
# seule fois, sous un délai de 5 secondes : un tube nommé substitué après le
# test « -f » bloquerait sinon root à l'ouverture, sans fin ni redémarrage.
# Le contenu refusé n'est pas cité : root lit le fichier, qui peut être un
# lien vers un fichier qu'Odoo ne lit pas.
lire_version() {
  local fichier="${prefixe}/.erplibre-version"
  version=""
  if [[ -f "${fichier}" ]]; then
    version=$(timeout 5 head -c 256 -- "${fichier}" 2>/dev/null |
      tr -d '[:space:]') || version=""
  fi
  if [[ ! "${version}" =~ ^odoo[0-9]+\.[0-9]+_python[0-9]+(\.[0-9]+)*$ ]]; then
    echo "Erreur : ${fichier} ne porte pas un nom de venv d'Odoo comme « odoo18.0_python3.12.16 » ($1) ; Odoo ne démarre pas." >&2
    exit 1
  fi
}

# resoudre_venv NOM VARIABLE : écrit dans « venv » le chemin résolu de
# « ${prefixe}/.venv.NOM » ; sort en 1, Odoo non lancé, s'il manque ou si un
# lien le mène ailleurs que sur ce nom même, enfant direct du préfixe résolu.
resoudre_venv() {
  local base
  base=$(realpath -e -- "${prefixe}") || base=""
  venv=$(realpath -e -- "${prefixe}/.venv.$1") || venv=""
  if [[ -z "${base}" || "${venv}" != "${base%/}/.venv.$1" ]]; then
    echo "Erreur : ${prefixe}/.venv.$1 n'est pas un venv du préfixe ${prefixe} ($2) ; Odoo ne démarre pas." >&2
    exit 1
  fi
}

# installer VARIABLE NOM : pip installe la liste de VARIABLE avec le python
# du venv « .venv.NOM » du préfixe. En root, pip tourne sous le propriétaire
# du venv, ou en root dans un venv que venv_sur_pour_root accepte ; sort en
# 1, Odoo non lancé, sur un venv de root qu'elle refuse, ou si pip refuse.
# L'uid et le gid viennent d'un seul stat : le compte du préfixe peut
# renommer un autre venv sur ce chemin, et deux lectures pourraient alors
# associer l'uid de l'un au gid de l'autre.
installer() {
  local variable="$1" nom="$2" exigences venv python ids proprio groupe sous=()
  read -r -d '' -a exigences <<<"${!variable:-}" || true
  ((${#exigences[@]})) || return 0
  resoudre_venv "${nom}" "${variable}"
  python="${venv}/bin/python"
  if [[ "$(id -u)" == 0 ]]; then
    ids=$(stat -c '%u %g' -- "${venv}")
    proprio=${ids% *}
    groupe=${ids#* }
    if [[ "${proprio}" != 0 ]]; then
      sous=(setpriv --reuid="${proprio}" --regid="${groupe}"
        --clear-groups env HOME="$(getent passwd "${proprio}" | cut -d: -f6)")
    elif ! venv_sur_pour_root "${venv}"; then
      echo "Erreur : ${venv} appartient à root, mais un autre compte peut substituer ce que root exécuterait, dans le venv ou dans son interpréteur de base (${variable}) ; Odoo ne démarre pas." >&2
      exit 1
    fi
  fi
  echo "pip extra (${python}) : ${exigences[*]}"
  if ! "${sous[@]}" "${python}" -I -m pip install --disable-pip-version-check \
    --no-input --no-cache-dir "${exigences[@]}"; then
    echo "Erreur : pip n'a pas installé ${variable} ; Odoo ne démarre pas." >&2
    exit 1
  fi
}

installer_apt
installer PIP_EXTRA_REQUIREMENTS_ERPLIBRE erplibre
if [[ -n "${PIP_EXTRA_REQUIREMENTS_ODOO:-}" ]]; then
  lire_version PIP_EXTRA_REQUIREMENTS_ODOO
  installer PIP_EXTRA_REQUIREMENTS_ODOO "${version}"
fi

if [[ "$(id -u)" == 0 && "${compte}" != root ]]; then
  exec setpriv --reuid="$(id -u "${compte}")" --regid="$(id -g "${compte}")" \
    --init-groups env HOME="$(getent passwd "${compte}" | cut -d: -f6)" \
    "${suite}" "$@"
fi
exec "${suite}" "$@"
