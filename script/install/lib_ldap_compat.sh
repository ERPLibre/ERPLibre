#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque SOURÇABLE : rendre libldap_r aux extensions qui l'exigent.
#
# OpenLDAP 2.5 a fondu libldap_r dans libldap, devenue sûre en multitâche.
# pyldap 2.4 — épinglé par Odoo 10, 11 et 12 — se lie encore à -lldap_r, et sa
# compilation s'arrête sur « cannot find -lldap_r » là où le système ne livre
# plus de lien de compatibilité (Debian le livre, Fedora non).

# el_ldap_r_compat <répertoire>
#
# Là où le compilateur ne trouve pas libldap_r mais trouve libldap, pose dans
# <répertoire> un lien libldap_r.so vers libldap et l'ajoute à LDFLAGS.
# L'extension compilée dépend alors du SONAME réel, libldap.so.2. Ailleurs,
# ne fait rien. Rend toujours 0 : l'absence de gcc ou de libldap se dira à la
# compilation, avec le vrai message.
el_ldap_r_compat() {
  local dir="$1" ldap_r ldap
  command -v gcc > /dev/null 2>&1 || return 0
  ldap_r="$(gcc -print-file-name=libldap_r.so 2> /dev/null)"
  ldap="$(gcc -print-file-name=libldap.so 2> /dev/null)"
  if [ "${ldap_r}" != "libldap_r.so" ] || [ ! -e "${ldap}" ]; then
    return 0
  fi
  mkdir -p "${dir}" && ln -sf "${ldap}" "${dir}/libldap_r.so" || return 0
  # Absolu : Poetry compile chaque paquet depuis un répertoire temporaire, où
  # un -L relatif au dépôt ne mène nulle part.
  dir="$(cd "${dir}" && pwd)" || return 0
  export LDFLAGS="${LDFLAGS:+${LDFLAGS} }-L${dir}"
  return 0
}
