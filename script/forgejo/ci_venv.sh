#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Pose .venv.erplibre d'un checkout de CI : un lien vers un venv persistant,
# hors de l'espace de travail du job, rebâti seulement quand la version de
# Python ou les dépendances changent.
#
# Le venv vit sous « $EL_CI_CACHE/venv/<version>-<clé> » (défaut :
# ~/.cache/erplibre-ci). La clé est l'empreinte de
# conf/python-erplibre-version et de requirement/erplibre_require-ments.txt.
# Un venv n'est pas déplaçable : il se bâtit à son chemin définitif, et le
# job l'atteint par un lien. Python retrouve pyvenv.cfg à travers le lien du
# dossier.
#
# Le marqueur « .erplibre-ci-pret » ne s'écrit qu'après pip : un venv
# interrompu se rebâtit. Au-delà des EL_CI_VENV_KEEP venvs les plus récents
# (défaut : 3), les plus anciens partent, jamais celui de ce job. Un verrou
# sérialise les jobs qui bâtissent.
#
# Ne se sert que des primitives du dépôt : install_venv.sh et
# el_pip_install. Rend 0 quand .venv.erplibre/bin/python s'exécute.
set -euo pipefail

cd "$(dirname "$0")/../.."

Red='\033[0;31m'
Color_Off='\033[0m'
say() { echo -e "   $*"; }
die() { echo -e "   ${Red}✗ $*${Color_Off}" >&2; exit 1; }

# shellcheck source=script/install/lib_non_interactive.sh
. ./script/install/lib_non_interactive.sh
export EL_NON_INTERACTIVE=1 EL_INSTALL_MISE="${EL_INSTALL_MISE:-1}"
el_non_interactive_env

VENV=$(xargs < conf/python-erplibre-venv)
VERSION=$(xargs < conf/python-erplibre-version)
RACINE_CACHE="${EL_CI_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/erplibre-ci}/venv"
GARDER="${EL_CI_VENV_KEEP:-3}"
case "$GARDER" in
    ''|*[!0-9]*|0) die "EL_CI_VENV_KEEP : entier >= 1" ;;
esac
CLE=$(cat conf/python-erplibre-version requirement/erplibre_require-ments.txt \
    | sha256sum | cut -c1-16)
CIBLE="$RACINE_CACHE/$VERSION-$CLE"
MARQUE="$CIBLE/.erplibre-ci-pret"

# Refusé avant le verrou et la construction : un vrai dossier ne se
# remplace pas par un lien, et rien ne se bâtit pour un checkout qui ne
# pourrait pas le recevoir.
if [ -e "$VENV" ] && [ ! -L "$VENV" ]; then
    die "$VENV existe et n'est pas un lien : refus"
fi

mkdir -p "$RACINE_CACHE"
exec 9>"$RACINE_CACHE/.verrou"
flock -w 3600 9 || die "verrou $RACINE_CACHE/.verrou tenu plus d'une heure"

if [ ! -f "$MARQUE" ] || ! "$CIBLE/bin/python" -c '' 2>/dev/null; then
    case "$CIBLE" in
        "$RACINE_CACHE"/?*) rm -rf "$CIBLE" ;;
        *) die "cible hors cache : $CIBLE" ;;
    esac
    say "venv à bâtir : $CIBLE"
    ./script/install/install_venv.sh ERPLibre "$CIBLE" "$VERSION"
    # shellcheck source=script/install/lib_pip_provider.sh
    . ./script/install/lib_pip_provider.sh
    el_pip_install "$CIBLE" -r requirement/erplibre_require-ments.txt
else
    say "venv repris : $CIBLE"
fi
touch "$MARQUE"
ln -sfn "$CIBLE" "$VENV"

# Le tri par date du marqueur : « touch » vient de rendre CIBLE le plus
# récent, et il est de toute façon épargné par son nom. Seul CIBLE est
# protégé : le verrou se rend avant les tests, et un venv retiré ici peut
# être celui d'un job concurrent en pleine exécution. D'où un runner à un
# seul job à la fois (install_forgejo_runner.sh refuse une autre
# FORGEJO_RUNNER_CAPACITY).
rang=0
while IFS= read -r marque; do
    rang=$((rang + 1))
    [ "$rang" -le "$GARDER" ] && continue
    vieux=$(dirname "$marque")
    [ "$vieux" = "$CIBLE" ] && continue
    case "$vieux" in
        "$RACINE_CACHE"/?*)
            say "venv retiré : $vieux"
            rm -rf "$vieux"
            ;;
    esac
done < <(ls -1t "$RACINE_CACHE"/*/.erplibre-ci-pret 2>/dev/null || true)

exec 9>&-
"$VENV/bin/python" -c '' || die "$VENV/bin/python ne s'exécute pas"
