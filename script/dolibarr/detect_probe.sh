#!/bin/sh
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Sonde de détection Dolibarr, en POSIX sh : lecture seule, aucun
# privilège demandé, aucun secret affiché. detect.py l'envoie sur stdin
# (« sh -s -- <profondeur> <racine>… ») : un seul aller-retour par hôte.
#
#   sh detect_probe.sh <profondeur> [<racine>…]
#
# Sortie, une ligne par fait, champs séparés par une tabulation :
#   DOLIBARR   yes | no | denied   (denied : rien trouvé, des dossiers illisibles)
#   INSTALL    chemin version conf db_type db_host db_name url data_root
#   CONTAINER  moteur nom image état
# conf vaut readable, unreadable ou absent. De conf.php, seules des clés
# nommées sont extraites : le mot de passe de la base n'est jamais lu.

depth=${1:-7}
[ $# -gt 0 ] && shift
[ $# -gt 0 ] || set -- /var/www /usr/share /opt /srv /home /var/lib
errors=$(mktemp 2>/dev/null) || errors=/tmp/dolibarr_probe.$$
trap 'rm -f "$errors"' EXIT

# conf_value <fichier> <clé> : la valeur de « $<clé> = '…' ».
conf_value() {
    sed -n "s/^[[:space:]]*\$$2[[:space:]]*=[[:space:]]*['\"]\([^'\"]*\)['\"].*/\1/p" "$1" |
        head -n 1
}

# define_value <fichier> <constante> : la valeur de define('<constante>', '…').
define_value() {
    sed -n "s/.*define([[:space:]]*['\"]$2['\"][[:space:]]*,[[:space:]]*['\"]\([0-9][0-9.]*\)['\"].*/\1/p" "$1" |
        head -n 1
}

version_of() {
    if [ -f "$1/version.inc.php" ]; then
        major=$(define_value "$1/version.inc.php" DOL_MAJOR_VERSION)
        minor=$(define_value "$1/version.inc.php" DOL_MINOR_VERSION)
        if [ -n "$major" ]; then
            echo "$major.$minor"
            return
        fi
    fi
    define_value "$1/filefunc.inc.php" DOL_VERSION
}

installs=$(
    for root in "$@"; do
        [ -d "$root" ] || continue
        find "$root" -maxdepth "$depth" \
            \( -name .git -o -name node_modules -o -name .cache \
            -o -name '.venv*' -o -name proc \) -prune \
            -o -name master.inc.php -type f -print 2>>"$errors"
    done | while IFS= read -r master; do
        dir=${master%/master.inc.php}
        [ -f "$dir/filefunc.inc.php" ] && [ -f "$dir/main.inc.php" ] || continue
        conf="$dir/conf/conf.php"
        db_type= db_host= db_name= url= data=
        if [ -r "$conf" ]; then
            state=readable
            db_type=$(conf_value "$conf" dolibarr_main_db_type)
            db_host=$(conf_value "$conf" dolibarr_main_db_host)
            db_name=$(conf_value "$conf" dolibarr_main_db_name)
            url=$(conf_value "$conf" dolibarr_main_url_root)
            data=$(conf_value "$conf" dolibarr_main_data_root)
        elif [ -e "$conf" ]; then
            state=unreadable
        else
            state=absent
        fi
        printf 'INSTALL\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$dir" \
            "$(version_of "$dir")" "$state" "$db_type" "$db_host" \
            "$db_name" "$url" "$data"
    done
)

containers=$(
    for engine in docker podman; do
        command -v "$engine" >/dev/null 2>&1 || continue
        "$engine" ps -a --format '{{.Names}}|{{.Image}}|{{.Status}}' 2>/dev/null |
            grep -i dolibarr | while IFS='|' read -r name image status; do
                printf 'CONTAINER\t%s\t%s\t%s\t%s\n' "$engine" "$name" \
                    "$image" "$status"
            done
    done
)

if [ -n "$installs$containers" ]; then
    status=yes
elif grep -q 'Permission denied' "$errors" 2>/dev/null; then
    status=denied
else
    status=no
fi
printf 'DOLIBARR\t%s\n' "$status"
[ -n "$installs" ] && printf '%s\n' "$installs"
[ -n "$containers" ] && printf '%s\n' "$containers"
exit 0
