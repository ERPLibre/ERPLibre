#!/usr/bin/env bash
# Désinstaller un thème comme Odoo le fait lui-même.
#
# « ./run.sh --uninstall theme_x » retire le MODULE, pas le THÈME. Choisir un
# thème (button_choose_theme, ce que pose --install-theme) fait DEUX choses :
# copier ses vues et ressources dans chaque site, et écrire dans
# user_values.scss une personnalisation qui DÉFINIT $o-theme-font-number et
# ses trois voisines. Le chemin de retrait d'Odoo, _theme_remove(), défait les
# deux.
#
# Le désinstaller sans lui laisse donc les copies, et surtout n'écrit jamais
# ces définitions. Mesuré sur une migration réelle 12 -> 13 : le bundle
# web.assets_frontend s'arrête sur « Undefined variable: $o-theme-font-number
# ». La variable venait des fichiers option_font_body_* d'Odoo 12, supprimés
# en 13.0 ; seul le thème la redéfinissait encore, et le retirer a mis à nu
# une personnalisation figée depuis des années.
#
# Usage : ./script/addons/uninstall_addons_theme.sh <base> <theme> [config]

Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <database> <theme_module> [config]"
  exit 1
fi

DATABASE="$1"
THEME="$2"
CONFIG="${3:-./config.conf}"

if [[ $# -eq 3 ]]; then
  ./script/addons/check_addons_exist.py -m "$THEME" -c "$3"
else
  ./script/addons/check_addons_exist.py -m "$THEME"
fi
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} check_addons_exist.py into uninstall_addons_theme.sh"
  exit 1
fi

echo "Unload theme '$THEME' from every website of BD '$DATABASE'"

# Le déchargement passe par le shell : _theme_remove() n'a pas d'option de
# ligne de commande, et l'écrire ici évite d'ajouter une option au fork pour
# chaque version d'Odoo. Les journaux se mêlent à la sortie, d'où la
# sentinelle : on ne conclut que sur ce qui la suit.
./odoo_bin.sh shell -c "$CONFIG" -d "$DATABASE" --no-http --log-level=warn <<PYTHON
theme_name = "$THEME"
Module = env["ir.module.module"]
theme = Module.search([("name", "=", theme_name)], limit=1)
if not theme:
    print("ERPLIBRE_THEME_UNLOAD: unknown %s" % theme_name)
else:
    lst_website = env["website"].search([])
    for website in lst_website:
        # _theme_remove décharge le thème COURANT du site et, avant tout,
        # rappelle _reset_default_config() : c'est cet appel qui écrit
        # font-number & co. dans user_values.scss. Il vaut même quand le
        # site n'a plus de thème — c'est précisément le cas à réparer.
        theme.with_context(website_id=website.id)._theme_remove(website)
    env.cr.commit()
    print("ERPLIBRE_THEME_UNLOAD: done %s website(s)" % len(lst_website))
PYTHON

retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} odoo_bin.sh shell into uninstall_addons_theme.sh"
  exit 1
fi

echo "Uninstall theme module '$THEME' on BD '$DATABASE'"

if [[ $# -eq 3 ]]; then
  ./run.sh --no-http --stop-after-init -d "$DATABASE" --uninstall "$THEME" -c "$3"
else
  ./run.sh --no-http --stop-after-init -d "$DATABASE" --uninstall "$THEME"
fi

retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo -e "${Red}Error${Color_Off} run.sh into uninstall_addons_theme.sh"
  exit 1
fi

# Ce que le déchargement ne prend pas : les pièces jointes que le thème a
# laissées sous son propre chemin. Elles ne cassent rien tant que ses vues
# sont parties, mais elles survivent à toutes les migrations suivantes et
# personne ne sait plus d'où elles viennent. On les signale, on ne les
# supprime pas : leur contenu peut être la seule trace d'une personnalisation.
./script/addons/theme_leftover.py -d "$DATABASE" -t "$THEME"
