#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque SOURCÉE par les installeurs, depuis la racine du dépôt, une
# fois PostgreSQL installé et démarré : el_postgres_role sous Linux,
# el_postgres_role_local sous macOS.
#
# el_postgres_role <rôle> : rend 0 quand le rôle PostgreSQL <rôle> existe en
# superutilisateur — déjà là, ou créé ici. Sinon, le dit avec la commande à
# taper, et rend 1 : l'installeur s'arrête plutôt que de se déclarer réussi
# devant un Odoo qui répondra « Internal Server Error » à chaque page, faute
# de rôle pour se connecter.
#
# Devient root par sudo, puis postgres par runuser — ni « su - postgres »,
# ni « sudo -u postgres ». su vérifie le compte CIBLE par PAM, et un compte
# système verrouillé (« u! » de systemd-sysusers, expiré au jour 1 de
# l'époque Unix, comme celui d'Arch) le refuse. « sudo -u postgres » vise
# postgres : sous « Defaults targetpw » (sudoers par défaut d'openSUSE), il
# demande le mot de passe de postgres, que personne n'a. « sudo runuser »
# vise root, dont le mot de passe est déjà en cache, et runuser lancé par
# root n'authentifie ni ne vérifie le compte. Les commandes partent de « / » :
# le répertoire courant de l'installeur est souvent illisible pour postgres,
# et psql s'en plaindrait à chaque appel.

el_postgres_role() {
  local role="$1"
  if (cd / && printf "SELECT 1 FROM pg_roles WHERE rolname = :'r'\n" |
    sudo runuser -u postgres -- psql -XAt -v r="${role}") 2>/dev/null |
    grep -qx 1; then
    echo "Rôle PostgreSQL « ${role} » déjà présent."
    return 0
  fi
  if (cd / && sudo runuser -u postgres -- createuser -s "${role}"); then
    echo "Rôle PostgreSQL « ${role} » créé."
    return 0
  fi
  echo "ERREUR : le rôle PostgreSQL « ${role} » n'a pas pu être créé."
  echo "  Sans lui, Odoo répond « Internal Server Error » à chaque page."
  echo "  Vérifiez que PostgreSQL tourne (systemctl status postgresql), puis,"
  echo "  sur cette machine :"
  echo "    sudo runuser -u postgres -- createuser -s ${role}"
  return 1
}

# el_postgres_role_local <rôle> : la même chose, pour un PostgreSQL qui tourne
# sous le compte de l'usager — celui de Homebrew sous macOS, dont initdb crée
# un rôle superutilisateur au nom de ce compte. Il n'y a là ni compte
# « postgres » ni runuser : psql et createuser partent du compte courant, sur
# la base « postgres » que porte tout cluster. Un serveur qui vient d'être
# lancé n'accepte pas encore de connexion : pg_isready l'attend jusqu'à 30 s.
el_postgres_role_local() {
  local role="$1" i
  if command -v pg_isready >/dev/null 2>&1; then
    for i in $(seq 1 30); do
      pg_isready -q -d postgres 2>/dev/null && break
      sleep 1
    done
  fi
  if printf "SELECT 1 FROM pg_roles WHERE rolname = :'r'\n" |
    psql -d postgres -XAt -v r="${role}" 2>/dev/null |
    grep -qx 1; then
    echo "Rôle PostgreSQL « ${role} » déjà présent."
    return 0
  fi
  if createuser -s "${role}"; then
    echo "Rôle PostgreSQL « ${role} » créé."
    return 0
  fi
  echo "ERREUR : le rôle PostgreSQL « ${role} » n'a pas pu être créé."
  echo "  Sans lui, Odoo répond « Internal Server Error » à chaque page."
  echo "  Vérifiez que PostgreSQL tourne (brew services list), puis, sur"
  echo "  cette machine :"
  echo "    createuser -s ${role}"
  return 1
}
