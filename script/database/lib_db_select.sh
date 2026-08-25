#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque SOURÇABLE : quelle base de données démarrer.
#
# « ./run.sh » sans argument démarrait Odoo sans base, et l'on choisissait
# dans le gestionnaire web. Quand il n'y a qu'une base, la question ne se
# pose pas ; quand il y en a quinze, un menu au terminal vaut mieux qu'une
# page web.
#
# TOUT ce qui s'affiche part sur stderr. Sur stdout, UNIQUEMENT le nom
# retenu : l'appelant lit `el_db_select` par substitution de commande, et
# un menu écrit sur stdout deviendrait une partie du nom de la base.
#
# Aucun `set` ici : une bibliothèque sourcée impose ses options à son hôte,
# et run.sh lit `$ODOO_MODE_TEST` sans valeur par défaut — `set -u` le
# tuerait avant tout le reste.

# Les couleurs peuvent déjà venir de l'hôte ; ne pas les écraser.
: "${Red:=\033[0;31m}"
: "${Yellow:=\033[0;33m}"
: "${Color_Off:=\033[0m}"

_el_db_say() {
  echo -e "$*" >&2
}

_el_db_tty() {
  # Deux descripteurs, et le second est stderr — PAS stdout.
  #
  # `validate_to_continue.sh` teste stdout parce qu'il y écrit sa question.
  # Ici la question part sur stderr, et l'appelant nous lit par
  # substitution de commande : dans `$( … )`, stdout est TOUJOURS un tube,
  # donc `-t 1` serait faux même devant un vrai terminal et le menu ne
  # s'ouvrirait jamais. Ce qu'il faut savoir, c'est « la personne verra-
  # t-elle l'invite », et l'invite sort par stderr.
  #
  # stdin compte tout autant : sans lui, `read` ne rendrait jamais rien.
  # Le TUI de todo.py met stdout ET stderr en tube en laissant stdin
  # intact — c'est le cas que ce garde doit refuser.
  #
  # Fonction isolée pour qu'un test puisse la remplacer sans pseudo-terminal.
  [ -t 0 ] && [ -t 2 ]
}

el_db_already_chosen() {
  # L'appelant a-t-il déjà nommé sa base ? Les quatre formes qu'optparse
  # accepte, plus « -d » nu en fin de ligne — ce que produit
  # « ./run.sh -d $(bd) » de conf/make.robotlibre.Makefile quand bd est
  # vide. Dans tous ces cas on se retire : c'est son intention, pas la
  # nôtre, et on ne complète pas un « -d » resté sans valeur.
  while [ $# -gt 0 ]; do
    case "$1" in
      -d | -d?* | --database | --database=*) return 0 ;;
    esac
    shift
  done
  return 1
}

el_db_config_has_name() {
  # Une configuration de production nomme sa base. L'option de ligne de
  # commande l'emporte sur le fichier : injecter « -d » par-dessus
  # écraserait ce choix en silence.
  local fichier="$1"
  [ -f "${fichier}" ] || return 1
  grep -Eq '^[[:space:]]*db_name[[:space:]]*=[[:space:]]*[^[:space:]]' \
    "${fichier}" || return 1
  # « False » et « None » sont la façon d'Odoo d'écrire « aucune ».
  if grep -Eq \
    '^[[:space:]]*db_name[[:space:]]*=[[:space:]]*(False|false|None)[[:space:]]*$' \
    "${fichier}"; then
    return 1
  fi
  return 0
}

el_db_list() {
  # Les bases, une par ligne. Sortie non nulle si la SONDE a échoué — et
  # alors on ne rend rien plutôt que d'inventer.
  #
  # stderr jeté, jamais fusionné : le CLI « db » n'appelle pas
  # parse_config(), donc aucun journal n'est configuré et tout part nu sur
  # stderr. Fusionner ferait de chaque ligne d'une trace un nom de base —
  # le défaut que script/todo/database_manager.py a déjà dû corriger.
  #
  # Le mode couverture est neutralisé pour ce seul appel : sinon la sonde
  # se mesure elle-même et sème un .coverage.* dans le rapport.
  local brut retenu
  brut="$(ODOO_MODE_COVERAGE= ./odoo_bin.sh db --list 2>/dev/null)" || return 1
  # « _cache_ » nomme les bases-modèles, pas des bases de travail. Sur une
  # machine qui vient de lancer les tests, ce peut être la SEULE : sans ce
  # filtre, la règle « une seule base » démarrerait Odoo sur un modèle.
  retenu="$(printf '%s\n' "${brut}" \
    | tr -d '\r' \
    | grep -v '^[[:space:]]*$' \
    | grep -v '^_cache_')"
  [ -n "${retenu}" ] && printf '%s\n' "${retenu}"
  return 0
}

el_db_choose() {
  # Le menu, entièrement sur stderr ; le nom retenu sur stdout.
  #
  # Numérotation à partir de 1 et « [0] » pour annuler : le vocabulaire
  # des menus Python du projet, pour qu'on reconnaisse le même produit.
  local -a bases=("$@")
  local rang nom choix
  while true; do
    _el_db_say ""
    _el_db_say "🗄  ${#bases[@]} bases de données. Laquelle démarrer ?"
    rang=1
    for nom in "${bases[@]}"; do
      _el_db_say "  [${rang}] ${nom}"
      rang=$((rang + 1))
    done
    _el_db_say "  [0] Annuler"
    printf 'Choix : ' >&2
    # shellcheck disable=SC2162
    if ! read -r choix; then
      # Ctrl-D : finir la ligne avant de partir, sinon l'invite reste
      # collée au shell qui reprend la main.
      _el_db_say ""
      return 130
    fi
    case "${choix}" in
      0) return 130 ;;
      "" | *[!0-9]*) ;;
      *)
        if [ "${choix}" -ge 1 ] && [ "${choix}" -le "${#bases[@]}" ]; then
          printf '%s\n' "${bases[$((choix - 1))]}"
          return 0
        fi
        ;;
    esac
    _el_db_say "${Red}Choix invalide${Color_Off} :" \
      "un nombre entre 0 et ${#bases[@]}."
  done
}

el_db_select() {
  # Le nom de la base à démarrer, sur stdout — ou rien. 130 si l'on renonce.
  #
  # Les gardes vont de la moins chère à la plus chère : la sonde coûte
  # 0,8 s (l'import d'Odoo, pas la requête) et ne se paie que lorsqu'elle
  # peut servir. Sur tous les chemins automatisés, zéro appel.
  #
  # `explicite` distingue « --auto-erplibre a été demandé » de « run.sh a
  # simplement reçu zéro argument ». Le défaut implicite doit rester
  # timide : systemd lance « /bin/bash …/run.sh » SANS argument, avec
  # Restart=always — un comportement neuf s'y déclencherait à chaque
  # démarrage de production, sans que personne l'ait demandé.
  local config="$1"
  local sans_cli="$2"
  local explicite="$3"
  shift 3

  el_db_already_chosen "$@" && return 0
  el_db_config_has_name "${config}" && return 0

  # Sans demande explicite, il faut un terminal des deux côtés pour que la
  # sélection s'arme du tout. Demandée, elle peut servir sans terminal —
  # mais seulement là où aucune question n'est posée.
  if [ "${explicite}" != "1" ] && ! _el_db_tty; then
    return 0
  fi

  local liste
  if ! liste="$(el_db_list)"; then
    _el_db_say "${Yellow}⚠${Color_Off} Impossible de lister les bases ;" \
      "Odoo démarre sans base présélectionnée."
    return 0
  fi

  local -a bases=()
  while IFS= read -r nom; do
    [ -n "${nom}" ] && bases+=("${nom}")
  done <<< "${liste}"

  if [ "${#bases[@]}" -eq 0 ]; then
    _el_db_say "${Yellow}⚠${Color_Off} Aucune base de données ;" \
      "Odoo démarre sur son gestionnaire web."
    return 0
  fi

  if [ "${#bases[@]}" -eq 1 ]; then
    _el_db_say "🗄  Une seule base : ${bases[0]}"
    printf '%s\n' "${bases[0]}"
    return 0
  fi

  if [ "${sans_cli}" = "1" ]; then
    _el_db_say "${Yellow}⚠${Color_Off} ${#bases[@]} bases et" \
      "--no-cli-erplibre : aucune n'est présélectionnée."
    return 0
  fi
  if ! _el_db_tty; then
    _el_db_say "${Yellow}⚠${Color_Off} ${#bases[@]} bases, mais pas de" \
      "terminal pour choisir : aucune n'est présélectionnée."
    return 0
  fi

  el_db_choose "${bases[@]}"
}
