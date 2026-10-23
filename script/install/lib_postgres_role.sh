#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque SOURCÉE par les installeurs Linux, depuis la racine du dépôt,
# une fois PostgreSQL installé et démarré.
#
# el_postgres_role <rôle> : rend 0 quand le rôle PostgreSQL <rôle> existe en
# superutilisateur — déjà là, promu ici, ou créé ici. Sinon, le dit avec la
# commande à taper, et rend 1 : l'installeur s'arrête plutôt que de se
# déclarer réussi devant un Odoo qui répondra « Internal Server Error » à
# chaque page, faute de rôle pour se connecter.
#
# Un rôle présent mais SANS rolsuper (créé par un « createuser » sans -s) ne
# suffit pas : Odoo s'y connecte, puis échoue à créer sa base. Il est promu
# par ALTER ROLE ... SUPERUSER plutôt que tenu pour bon.
#
# Le nom du rôle n'entre jamais dans le texte SQL : il passe en variable psql
# (-v r=...), interpolée par psql lui-même — :'r' en littéral, :"r" en
# identifiant —, ce qui le protège des guillemets qu'il contiendrait.
# ON_ERROR_STOP fait rendre à psql un code non nul quand l'ALTER échoue ;
# sans lui, psql lisant son entrée standard rend 0 malgré l'erreur.
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
  local super
  # « t » : superutilisateur, « f » : rôle simple, vide : absent (ou psql
  # injoignable, ce que createuser dira ensuite).
  super="$( (cd / && printf "SELECT rolsuper FROM pg_roles WHERE rolname = :'r'\n" |
    sudo runuser -u postgres -- psql -XAt -v r="${role}") 2>/dev/null)"
  if [[ "${super}" == "t" ]]; then
    echo "Rôle PostgreSQL « ${role} » déjà présent."
    return 0
  fi
  if [[ "${super}" == "f" ]]; then
    if (cd / && printf "ALTER ROLE :\"r\" SUPERUSER\n" |
      sudo runuser -u postgres -- psql -XAq -v ON_ERROR_STOP=1 -v r="${role}"); then
      echo "Rôle PostgreSQL « ${role} » promu superutilisateur."
      return 0
    fi
    echo "ERREUR : le rôle PostgreSQL « ${role} » existe sans être"
    echo "  superutilisateur, et n'a pas pu être promu."
    echo "  Sans ce droit, Odoo ne peut pas créer sa base de données."
    echo "  L'erreur de psql est affichée plus haut ; une fois sa cause"
    echo "  corrigée, sur cette machine :"
    echo "    sudo runuser -u postgres -- psql -c 'ALTER ROLE \"${role}\" SUPERUSER'"
    return 1
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
