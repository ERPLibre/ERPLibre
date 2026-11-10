#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque SOURCÉE par install_debian_dependency.sh, depuis la racine du
# dépôt, APT_GET défini : quelle version majeure de PostgreSQL poser, la poser,
# et dire quand les bases restent sur un cluster plus ancien.
#
# el_pg_plancher : imprime la version majeure minimale. 16 pour toute version
# d'Odoo — une base d'Odoo 20 échoue en dessous sur « any_value() n'existe
# pas ». Le champ « postgresql_version » de l'entrée du catalogue
# (conf/supported_version_erplibre.json) de la version d'Odoo ACTIVE
# (.odoo-version) relève ce plancher, jamais ne l'abaisse. Sans .odoo-version
# — un clone neuf, avant sa première installation — la version par défaut du
# catalogue en tient lieu : c'est elle que l'installation posera ensuite.
# Sans ce champ ou sans python3, il reste 16. Le catalogue est lu par
# version_manager.py sur le Python du système : aucun venv n'existe encore.
#
# el_pg_installer : pose PostgreSQL. La version qu'apt offre déjà — celle de
# la distribution, ou de PGDG s'il est configuré — sert quand elle atteint le
# plancher ; sinon — Debian 12 livre la 15 — la version vient du
# dépôt officiel PostgreSQL (PGDG). PG_VERSION impose une version, par exemple
# « make install_os PG_VERSION=15 » pour une machine qui n'accueillera
# qu'Odoo 10 ou 11. Pose EL_PG_CHOISIE, la version majeure installée, et rend
# 1 quand apt échoue.
#
# el_pg_avis_ancien_cluster : poser une nouvelle version majeure ne migre
# rien. postgresql-common lui crée un cluster vide sur le premier port libre,
# et le port 5432 — celui que libpq, donc Odoo sans « db_port », joint par
# défaut — reste au cluster existant, comme le rôle qu'el_postgres_role y
# crée. Quand ce cluster est d'une version majeure antérieure à
# EL_PG_CHOISIE, la fonction le dit et nomme l'entrée du TODO qui migre ; sinon
# elle se tait. Rend toujours 0 : l'installation, elle, a réussi.

# Le port par défaut de libpq : le cluster qui l'occupe est celui qu'Odoo
# joint quand sa configuration ne nomme pas de port.
EL_PG_PORT_DEFAUT=5432

el_pg_plancher() {
  local plancher=16 odoo requise
  if [[ -r .odoo-version ]]; then
    odoo="$(tr -d '[:space:]' <.odoo-version)"
  else
    odoo="$(python3 ./script/todo/version_manager.py odoo_par_defaut \
      2>/dev/null)"
  fi
  if [[ -n "${odoo}" ]]; then
    requise="$(python3 ./script/todo/version_manager.py \
      postgresql_requise "${odoo}" 2>/dev/null)"
    if [[ "${requise}" =~ ^[0-9]+$ ]] && ((requise > plancher)); then
      plancher="${requise}"
    fi
  fi
  echo "${plancher}"
}

el_pg_installer() {
  local plancher distrib voulue
  plancher="$(el_pg_plancher)"
  distrib="$(LC_ALL=C apt-cache depends postgresql 2>/dev/null |
    sed -n 's/.*Depends: postgresql-\([0-9][0-9]*\)$/\1/p' | head -1)"
  voulue="${PG_VERSION:-}"
  if [[ -z "${voulue}" && -n "${distrib}" && "${distrib}" -ge "${plancher}" ]]; then
    echo "PostgreSQL ${distrib}, déjà disponible par apt."
    EL_PG_CHOISIE="${distrib}"
    # Le paquet versionné, jamais les méta-paquets « postgresql » et
    # « postgresql-contrib » : quand une source PGDG est déjà configurée, le
    # premier vient d'elle et le second de la distribution, qui tire alors son
    # propre serveur (la 15 sur Debian 12) en plus du choisi. contrib fait
    # partie de postgresql-<N> depuis la 10.
    ${APT_GET} install "postgresql-${distrib}" libpq-dev -y && return 0
  else
    voulue="${voulue:-${plancher}}"
    if [[ "${voulue}" != "${distrib}" ]]; then
      echo "PostgreSQL ${voulue} du dépôt PGDG (la distribution fournit ${distrib:-aucune version})."
      ${APT_GET} install postgresql-common -y &&
        sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y ||
        {
          echo "Ajout du dépôt PGDG en erreur."
          return 1
        }
    fi
    EL_PG_CHOISIE="${voulue}"
    ${APT_GET} install "postgresql-${voulue}" libpq-dev -y && return 0
  fi
  echo "apt-get install postgresql installation error."
  return 1
}

el_pg_avis_ancien_cluster() {
  local clusters ancien neuf
  [[ -n "${EL_PG_CHOISIE}" ]] || return 0
  command -v pg_lsclusters >/dev/null 2>&1 || return 0
  # pg_lsclusters -h : « version cluster port état propriétaire données
  # journal », une ligne par cluster. La comparaison se fait dans awk, en
  # nombres : une version « 9.6 » n'est pas un entier pour bash.
  clusters="$(pg_lsclusters -h 2>/dev/null)"
  ancien="$(awk -v n="${EL_PG_CHOISIE}" -v p="${EL_PG_PORT_DEFAUT}" \
    '$3 == p && $1 + 0 < n + 0 {print $1 "/" $2; exit}' <<<"${clusters}")"
  [[ -n "${ancien}" ]] || return 0
  neuf="$(awk -v n="${EL_PG_CHOISIE}" \
    '$1 + 0 == n + 0 {print $1 "/" $2 " (port " $3 ")"; exit}' <<<"${clusters}")"
  echo
  echo "⚠ PostgreSQL ${EL_PG_CHOISIE} est installé, mais RIEN n'a été migré :"
  echo "  les bases restent sur le cluster ${ancien} (port ${EL_PG_PORT_DEFAUT}),"
  echo "  et c'est lui qu'Odoo joint tant que sa configuration ne nomme pas"
  echo "  d'autre port."
  if [[ -n "${neuf}" ]]; then
    echo "  Le nouveau cluster est ${neuf}."
  fi
  echo "  Pour passer les bases sur PostgreSQL ${EL_PG_CHOISIE} :"
  echo "    TODO › Exécution › Database › « Mettre à niveau le serveur PostgreSQL »"
  echo "    (TODO › Execute › Database › \"Upgrade the PostgreSQL server\")"
  return 0
}
