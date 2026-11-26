#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Étape ERPLibre de l'installateur : pose ERPLibre sur le système cible, en
# root, DANS le chroot d'archinstall.
#
# erplibre-install-config ajoute devant ce texte un prélude de variables
# (EL_PROFILE_*, EL_GIT_*, EL_TTY, EL_LANG, EL_UNIT_TEMPLATE) et passe le
# tout comme unique « custom_commands » d'archinstall. archinstall écrit la
# commande dans /var/tmp/user-command.0.sh du système cible, la lance par
# « arch-chroot -S <cible> bash <fichier> », puis efface le fichier.
#
# Quatre contraintes en découlent :
#
# - Le script rend TOUJOURS 0. Un code non nul lève une exception dans
#   archinstall, qui saute alors genfstab : le système, GNOME compris, ne
#   démarrerait plus. Le verdict réel va dans EL_STATUS, que le mode
#   automatique relit une fois archinstall terminé.
# - « arch-chroot -S » lance la commande comme service transitoire
#   (systemd-run, RootDirectory) : /run y est un tmpfs vide, et systemctl
#   y refuse « start » tout en acceptant « enable ». PostgreSQL est donc
#   initialisé et démarré par pg_ctl, puis arrêté à la fin.
# - Le même service monte sur /tmp un tmpfs privé en mode 0755 : seul root
#   y écrit, et tout « mktemp » du compte échoue. el_chroot_tmp lui rend le
#   mode 1777 d'un /tmp ordinaire.
# - La sortie de la commande est captée par archinstall, qui ne l'affiche
#   pas : elle est recopiée dans EL_LOG et sur EL_TTY, la console où
#   l'installateur tourne.
#
# Le script se recopie dans /usr/local/sbin/erplibre-stage, prélude
# compris : relancé à la main sur le système démarré, il reprend où il a
# échoué (clone gardé, PostgreSQL démarré par systemctl).
#
# Codes de EL_STATUS : 0 réussi, 3 aucun compte utilisateur, 10 sudoers,
# 11 clone, 12 PostgreSQL, 13 commande du profil, 14 service erplibre,
# 15 autorité hors ligne.

EL_PROFILE_KEY="${EL_PROFILE_KEY:-}"
EL_PROFILE_LABEL="${EL_PROFILE_LABEL:-}"
EL_PROFILE_CMD="${EL_PROFILE_CMD:-}"
EL_PROFILE_SERVICE="${EL_PROFILE_SERVICE:-0}"
EL_PROFILE_POSTGRES="${EL_PROFILE_POSTGRES:-0}"
EL_GIT_URL="${EL_GIT_URL:-https://github.com/erplibre/erplibre}"
EL_GIT_BRANCH="${EL_GIT_BRANCH:-master}"
EL_TTY="${EL_TTY:-}"
EL_LANG="${EL_LANG:-fr}"
EL_UNIT_TEMPLATE="${EL_UNIT_TEMPLATE:-}"
# Installation hors ligne (erplibre_offline.stage_prelude) : EL_OFFLINE=1
# et l'autorité du paquet en base64 sur une ligne.
EL_OFFLINE="${EL_OFFLINE:-0}"
EL_OFFLINE_CA_B64="${EL_OFFLINE_CA_B64:-}"

EL_LOG=/var/log/erplibre-install.log
EL_STATUS_DIR=/var/lib/erplibre-install
EL_STATUS="${EL_STATUS_DIR}/status"
EL_SUDOERS=/etc/sudoers.d/90-erplibre-install
EL_RELAUNCH=/usr/local/sbin/erplibre-stage
EL_UNIT_FILE="${EL_UNIT_FILE:-/etc/systemd/system/erplibre.service}"
EL_PASSWD="${EL_PASSWD:-/etc/passwd}"
EL_TMP_DIR="${EL_TMP_DIR:-/tmp}"
EL_ROOT="${EL_ROOT:-}"
EL_OFFLINE_ANCHOR="${EL_ROOT}/etc/ca-certificates/trust-source/anchors/erplibre-offline.crt"
# npmrc global lu par npm sur Arch (voir erplibre_offline.NPMRC).
EL_OFFLINE_NPMRC="${EL_ROOT}/etc/npmrc"
EL_OFFLINE_NPMRC_MARK="# erplibre-offline"
EL_SYSTEM_BUNDLE=/etc/ssl/certs/ca-certificates.crt
EL_OFFLINE_ACTIVE=0
EL_PG_DATA=/var/lib/postgres/data
EL_PG_LOG=/var/lib/postgres/erplibre-install.log
EL_PG_STARTED=0
EL_IN_CHROOT=0
EL_USER=""
EL_HOME=""
EL_DIR=""
EL_TEE_PID=""

# el_say <français> <anglais> : une ligne dans la langue de l'installateur.
el_say() {
  if [[ "${EL_LANG}" == "en" ]]; then
    printf '%s\n' "$2"
  else
    printf '%s\n' "$1"
  fi
}

el_step() {
  printf '\n==== ERPLibre : '
  el_say "$1" "$2"
}

# Toute la sortie va au journal, à la console de l'installateur si elle
# s'ouvre en écriture, et à la sortie d'origine. Hors du chroot (relance à
# la main), la sortie d'origine est déjà le terminal de l'utilisateur et
# EL_TTY est ignoré. Le test « -t 1 » ne sert pas : archinstall lance
# l'étape sous un pty (pty.fork, puis systemd-run --pty), la sortie y est
# donc toujours un terminal que personne ne lit. Les descripteurs 3 et 4
# gardent la sortie d'origine : el_flush_output les rétablit puis attend tee,
# qui sinon serait tué avec le service transitoire avant d'avoir tout écrit.
el_setup_output() {
  mkdir -p "$(dirname "${EL_LOG}")"
  exec 3>&1 4>&2
  if [[ "${EL_IN_CHROOT}" != "1" ]]; then
    EL_TTY=""
  fi
  if [[ -n "${EL_TTY}" ]] && { true >>"${EL_TTY}"; } 2>/dev/null; then
    exec > >(tee -a "${EL_LOG}" "${EL_TTY}") 2>&1
  else
    exec > >(tee -a "${EL_LOG}") 2>&1
  fi
  EL_TEE_PID=$!
}

el_flush_output() {
  exec 1>&3 2>&4
  if [[ -n "${EL_TEE_PID}" ]]; then
    wait "${EL_TEE_PID}" 2>/dev/null || true
    EL_TEE_PID=""
  fi
}

# Dans le chroot d'archinstall, systemd n'est pas le PID 1 de cette racine :
# systemd-detect-virt le dit, et /run/systemd/system manque du /run vide
# que monte « arch-chroot -S ».
el_detect_chroot() {
  if systemd-detect-virt --chroot >/dev/null 2>&1 ||
    [[ ! -d /run/systemd/system ]]; then
    EL_IN_CHROOT=1
  fi
}

# /tmp du chroot ouvert à tous, collant, comme sur le système démarré. Le
# tmpfs est propre au service : le mode disparaît avec lui.
el_chroot_tmp() {
  if [[ "${EL_IN_CHROOT}" == "1" ]]; then
    chmod 1777 "${EL_TMP_DIR}"
  fi
}

# Premier compte de /etc/passwd dont l'UID est >= 1000, nobody (65534)
# exclu : c'est le compte créé dans le menu d'archinstall.
el_find_user() {
  local line
  line="$(awk -F: '$3 >= 1000 && $3 < 60000 { print $1 ":" $6; exit }' \
    "${EL_PASSWD}")"
  EL_USER="${line%%:*}"
  EL_HOME="${line#*:}"
  if [[ -z "${EL_USER}" || -z "${EL_HOME}" ]]; then
    EL_USER=""
    return 1
  fi
  EL_DIR="${EL_HOME}/git/erplibre"
}

# sudo sans mot de passe pour le compte, le temps de l'étape seulement :
# « make install_os » appelle sudo sans terminal. visudo valide le fichier
# avant qu'il ne soit en place ; el_cleanup le retire dans tous les cas.
el_sudoers_add() {
  local tmp="${EL_SUDOERS}.tmp"
  install -d -m 0750 /etc/sudoers.d || return 1
  printf '%s ALL=(ALL:ALL) NOPASSWD: ALL\n' "${EL_USER}" >"${tmp}" || return 1
  chmod 0440 "${tmp}" || return 1
  if ! visudo -cqf "${tmp}"; then
    rm -f -- "${tmp}"
    return 1
  fi
  mv -f -- "${tmp}" "${EL_SUDOERS}"
}

# --- SOURCE RÉSEAU -----------------------------------------------------
# Seul endroit qui décide d'où viennent le dépôt ERPLibre et, pour tout ce
# que l'étape lance, les paquets et les téléchargements. En ligne : le
# réseau de la cible tel quel, EL_GIT_URL et EL_GIT_BRANCH venant de
# profiles.json (« network_source »).
#
# Hors ligne (EL_OFFLINE=1, dans le chroot seulement) : le live sert déjà
# tout — DNS, détournement nft de la sortie 80/443 vers le mandataire du
# paquet, dépôt pacman — au chroot, qui partage son réseau ; EL_GIT_URL et
# EL_GIT_BRANCH sont ceux que le paquet a enregistrés. Reste à faire
# approuver l'autorité du paquet PAR LA CIBLE : ancre et faisceau système
# (git, pacman, curl), variables de el_offline_env pour ce qui l'ignore
# (pip, requests, uv, Node), et un npmrc global pour « sudo npm -g », dont
# sudo vide l'environnement. el_network_source_release retire les trois,
# et la cible n'approuve plus rien de plus qu'une installation en ligne.
el_network_source_prepare() {
  el_say "Source : ${EL_GIT_URL} (branche ${EL_GIT_BRANCH})" \
    "Source: ${EL_GIT_URL} (branch ${EL_GIT_BRANCH})"
  [[ "${EL_OFFLINE}" == "1" && "${EL_IN_CHROOT}" == "1" ]] || return 0
  el_say "Installation hors ligne : autorité du paquet approuvée le temps de l'étape" \
    "Offline install: payload authority trusted for the stage only"
  [[ -n "${EL_OFFLINE_CA_B64}" ]] || return 1
  EL_OFFLINE_ACTIVE=1
  install -d -m 0755 "$(dirname "${EL_OFFLINE_ANCHOR}")" || return 1
  printf '%s' "${EL_OFFLINE_CA_B64}" | base64 -d >"${EL_OFFLINE_ANCHOR}" ||
    return 1
  chmod 0644 "${EL_OFFLINE_ANCHOR}" || return 1
  el_trust_extract || return 1
  if [[ ! -e "${EL_OFFLINE_NPMRC}" ]]; then
    install -d -m 0755 "$(dirname "${EL_OFFLINE_NPMRC}")" || return 1
    printf '%s\ncafile=%s\naudit=false\nfund=false\nupdate-notifier=false\n' \
      "${EL_OFFLINE_NPMRC_MARK}" "${EL_SYSTEM_BUNDLE}" >"${EL_OFFLINE_NPMRC}" ||
      return 1
  fi
}

el_network_source_release() {
  [[ "${EL_OFFLINE_ACTIVE}" == "1" ]] || return 0
  rm -f -- "${EL_OFFLINE_ANCHOR}"
  if [[ -f "${EL_OFFLINE_NPMRC}" ]] &&
    grep -qxF -- "${EL_OFFLINE_NPMRC_MARK}" "${EL_OFFLINE_NPMRC}"; then
    rm -f -- "${EL_OFFLINE_NPMRC}"
  fi
  el_trust_extract || true
  EL_OFFLINE_ACTIVE=0
}

# Régénère le faisceau système depuis les ancres (p11-kit, paquet
# ca-certificates de base). Les tests le remplacent.
el_trust_extract() {
  trust extract-compat
}

# el_offline_env : les « VAR=valeur » ajoutées à l'environnement de la
# commande du profil hors ligne ; rien en ligne. Gardé en accord avec
# erplibre_offline.stage_env, que test_iso_offline compare.
el_offline_env() {
  [[ "${EL_OFFLINE_ACTIVE}" == "1" ]] || return 0
  printf '%s\n' \
    "SSL_CERT_FILE=${EL_SYSTEM_BUNDLE}" \
    "REQUESTS_CA_BUNDLE=${EL_SYSTEM_BUNDLE}" \
    "PIP_CERT=${EL_SYSTEM_BUNDLE}" \
    "CURL_CA_BUNDLE=${EL_SYSTEM_BUNDLE}" \
    "NODE_EXTRA_CA_CERTS=${EL_SYSTEM_BUNDLE}" \
    "UV_NATIVE_TLS=1" \
    "NPM_CONFIG_AUDIT=false" \
    "NPM_CONFIG_FUND=false" \
    "NPM_CONFIG_UPDATE_NOTIFIER=false"
}
# ------------------------------------------------------------------------

el_clone() {
  if [[ -d "${EL_DIR}/.git" ]]; then
    el_say "Dépôt existant gardé, sans mise à jour : ${EL_DIR}" \
      "Existing checkout kept, not updated: ${EL_DIR}"
    return 0
  fi
  runuser -u "${EL_USER}" -- mkdir -p "${EL_HOME}/git" || return 1
  (cd / && runuser -u "${EL_USER}" -- git clone --branch "${EL_GIT_BRANCH}" \
    -- "${EL_GIT_URL}" "${EL_DIR}") || return 1
  runuser -u "${EL_USER}" -- git -C "${EL_DIR}" log -1 --abbrev=12 \
    --format='   Commit : %h %s' 2>/dev/null || true
}

# PostgreSQL doit RÉPONDRE avant « make install_os » : el_postgres_role
# (script/install/lib_postgres_role.sh) y crée le rôle du compte par psql.
# install_arch_linux.sh teste PG_VERSION en tant que compte, qui ne lit pas
# le répertoire de données (0700) : il relance initdb, qui refuse un
# répertoire non vide, et son « || true » absorbe l'échec. C'est l'initdb
# d'ici, fait en root avant lui, qui crée le cluster. Son « systemctl
# enable --now » n'active que le service dans un chroot.
el_postgres_start() {
  pacman -S --needed --noconfirm postgresql || return 1
  if [[ ! -f "${EL_PG_DATA}/PG_VERSION" ]]; then
    install -d -o postgres -g postgres -m 0700 "${EL_PG_DATA}" || return 1
    (cd / && runuser -u postgres -- initdb --locale=C.UTF-8 \
      --encoding=UTF8 -D "${EL_PG_DATA}") || return 1
  fi
  systemctl enable postgresql.service || return 1
  if [[ "${EL_IN_CHROOT}" != "1" ]]; then
    systemctl start postgresql.service
    return
  fi
  # Le socket vit dans /run/postgresql, absent du /run vide du chroot.
  install -d -o postgres -g postgres -m 0755 /run/postgresql || return 1
  if (cd / && runuser -u postgres -- pg_ctl -D "${EL_PG_DATA}" status \
    >/dev/null 2>&1); then
    return 0
  fi
  (cd / && runuser -u postgres -- pg_ctl -D "${EL_PG_DATA}" \
    -l "${EL_PG_LOG}" -w -t 120 start) || return 1
  EL_PG_STARTED=1
}

el_postgres_stop() {
  if [[ "${EL_PG_STARTED}" == "1" ]]; then
    (cd / && runuser -u postgres -- pg_ctl -D "${EL_PG_DATA}" -m fast -w \
      stop) || true
    EL_PG_STARTED=0
  fi
}

# Locale du système cible (archinstall écrit /etc/locale.conf), C.UTF-8
# sinon.
el_target_lang() {
  local lang=""
  if [[ -f /etc/locale.conf ]]; then
    lang="$(sed -n 's/^LANG=//p' /etc/locale.conf | head -n1)"
    lang="${lang//\"/}"
  fi
  printf '%s\n' "${lang:-C.UTF-8}"
}

# Commande du profil, en tant que le compte, depuis le dépôt, avec un
# environnement de connexion reconstruit : runuser ne fait ni HOME ni PATH,
# et « arch-chroot -S » vide l'environnement. EL_NON_INTERACTIVE=1 et
# EL_INSTALL_MISE=1 sont ceux du chemin QEMU : aucune question, et le
# CPython précompilé de mise quand la distribution n'a pas la version
# voulue. L'entrée standard est /dev/null : une question oubliée échoue
# au lieu d'attendre.
#
# GIO_USE_VFS=local et GVFS_DISABLE_FUSE=1 : sans session, gsettings passe
# par un dbus-run-session qui active gvfsd, et gvfsd lance gvfsd-fuse au
# premier plan. Ce dernier survit au bus en gardant la sortie de la
# substitution « $( gsettings … ) » qui l'a lancé : le script appelant
# attend alors sans fin. gsettings n'a besoin que de dconf, pas de gvfs.
el_run_profile() {
  local -a offline=()
  mapfile -t offline < <(el_offline_env)
  runuser -u "${EL_USER}" -- env -i \
    HOME="${EL_HOME}" USER="${EL_USER}" LOGNAME="${EL_USER}" \
    SHELL=/bin/bash LANG="$(el_target_lang)" TERM="${TERM:-dumb}" \
    PATH="${EL_HOME}/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/bin" \
    EL_NON_INTERACTIVE=1 EL_INSTALL_MISE=1 \
    GIO_USE_VFS=local GVFS_DISABLE_FUSE=1 \
    "${offline[@]}" \
    bash -lc "cd \"\$HOME/git/erplibre\" && ${EL_PROFILE_CMD}" </dev/null
}

# Unité erplibre.service : le gabarit est celui de
# QemuInstallMixin._qemu_odoo_service_cmd, extrait à la construction de
# l'ISO. Ses variables y sont remplacées ici, SELinux en moins (Arch n'en
# a pas). Dans le chroot, « enable » suffit : le service démarre au
# premier démarrage, après postgresql.service qu'il requiert.
el_install_service() {
  local unit group
  if [[ -z "${EL_UNIT_TEMPLATE}" ]]; then
    el_say "Gabarit d'unité absent." "Unit template missing."
    return 1
  fi
  group="$(id -gn "${EL_USER}")" || return 1
  unit="${EL_UNIT_TEMPLATE}"
  # Remplacements entre guillemets : sans eux, bash 5.2 lit « & » dans le
  # texte de remplacement comme le motif trouvé.
  unit="${unit//'$SVC_USER'/"${EL_USER}"}"
  unit="${unit//'$SVC_GROUP'/"${group}"}"
  unit="${unit//'$SVC_DIR'/"${EL_DIR}"}"
  unit="${unit//'$SELINUX_LINE'/}"
  printf '%s\n' "${unit}" >"${EL_UNIT_FILE}" || return 1
  if [[ "${EL_IN_CHROOT}" == "1" ]]; then
    systemctl enable erplibre.service
  else
    systemctl daemon-reload && systemctl enable --now erplibre.service
  fi
}

# Dans le chroot, le compte n'a aucune session : tout processus encore à
# lui est un démon laissé par la commande du profil (gpg-agent de repo,
# service D-Bus activé…). Il garde la sortie vers tee ouverte, et
# el_flush_output attendrait tee sans fin. Hors du chroot, la session de
# l'utilisateur est peut-être ouverte : rien n'est tué.
el_reap_user() {
  if [[ "${EL_IN_CHROOT}" == "1" && -n "${EL_USER}" ]]; then
    pkill -KILL -u "${EL_USER}" 2>/dev/null || true
  fi
}

el_cleanup() {
  el_reap_user
  el_postgres_stop
  rm -f -- "${EL_SUDOERS}" "${EL_SUDOERS}.tmp"
  el_network_source_release
}

# La copie de relance tourne sur le système démarré, en ligne : les deux
# lignes hors ligne du prélude n'y passent pas — « EL_OFFLINE=1 » devient
# « EL_OFFLINE=0 », l'autorité du paquet est retirée — et la relance ne
# pose jamais d'ancre. Les motifs ne touchent que la forme du prélude
# (valeur nue, sans « ${ ») : les défauts du corps du script restent.
el_relaunch_filter() {
  sed -e 's/^EL_OFFLINE=1$/EL_OFFLINE=0/' \
    -e '/^EL_OFFLINE_CA_B64=[A-Za-z0-9+\/=]*$/d'
}

el_save_relaunch() {
  if [[ -f "$0" && "$0" != "${EL_RELAUNCH}" ]]; then
    install -d -m 0755 "$(dirname "${EL_RELAUNCH}")" 2>/dev/null || true
    el_relaunch_filter <"$0" >"${EL_RELAUNCH}" 2>/dev/null &&
      chmod 0750 "${EL_RELAUNCH}" 2>/dev/null || true
  fi
}

el_main() {
  el_step "profil « ${EL_PROFILE_LABEL} »" "profile \"${EL_PROFILE_LABEL}\""
  if [[ -z "${EL_PROFILE_CMD}" ]]; then
    el_say "Aucune commande ERPLibre pour ce profil." \
      "No ERPLibre command for this profile."
    return 0
  fi
  if ! el_find_user; then
    el_say "Aucun compte utilisateur (UID >= 1000) : ERPLibre n'est pas" \
      "No user account (UID >= 1000): ERPLibre is not installed."
    el_say "installé. GNOME l'est ; créer un compte, puis lancer" \
      "GNOME is. Create an account, then run"
    el_say "« sudo ${EL_RELAUNCH} »." "\"sudo ${EL_RELAUNCH}\"."
    return 3
  fi
  el_say "Compte : ${EL_USER} — dépôt : ${EL_DIR}" \
    "Account: ${EL_USER} — checkout: ${EL_DIR}"

  el_step "sudo temporaire" "temporary sudo"
  el_sudoers_add || return 10

  el_step "clone du dépôt" "cloning the repository"
  el_network_source_prepare || return 15
  el_clone || return 11

  if [[ "${EL_PROFILE_POSTGRES}" == "1" ]]; then
    el_step "PostgreSQL" "PostgreSQL"
    el_postgres_start || return 12
  fi

  el_step "${EL_PROFILE_CMD}" "${EL_PROFILE_CMD}"
  el_run_profile || return 13

  if [[ "${EL_PROFILE_SERVICE}" == "1" ]]; then
    el_step "service erplibre.service" "erplibre.service unit"
    el_install_service || return 14
  fi
  return 0
}

el_summary() {
  local rc="$1"
  printf '\n'
  printf '=%.0s' {1..70}
  printf '\n'
  if [[ "${rc}" == "0" ]]; then
    el_say "ERPLibre : installation RÉUSSIE (${EL_PROFILE_LABEL})." \
      "ERPLibre: installation SUCCEEDED (${EL_PROFILE_LABEL})."
    if [[ "${EL_PROFILE_SERVICE}" == "1" ]]; then
      el_say "Odoo démarre avec le système : http://localhost:8069" \
        "Odoo starts with the system: http://localhost:8069"
    fi
  else
    el_say "ERPLibre : installation ÉCHOUÉE (code ${rc})." \
      "ERPLibre: installation FAILED (code ${rc})."
    el_say "Le système et GNOME sont installés et démarrent quand même." \
      "The system and GNOME are installed and boot anyway."
    el_say "Une fois démarré, relancer : sudo ${EL_RELAUNCH}" \
      "Once booted, relaunch: sudo ${EL_RELAUNCH}"
  fi
  el_say "Journal : ${EL_LOG}" "Log: ${EL_LOG}"
  printf '=%.0s' {1..70}
  printf '\n'
}

# Sourcé (par les tests du dépôt), le script ne fait que définir ses
# fonctions.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  el_detect_chroot
  el_chroot_tmp
  el_setup_output
  trap 'el_cleanup' EXIT
  trap 'el_cleanup; exit 0' INT TERM
  el_save_relaunch
  el_main
  EL_RC=$?
  el_cleanup
  mkdir -p "${EL_STATUS_DIR}"
  printf 'rc=%s\nprofile=%s\n' "${EL_RC}" "${EL_PROFILE_KEY}" >"${EL_STATUS}"
  el_summary "${EL_RC}"
  el_flush_output
  exit 0
fi
