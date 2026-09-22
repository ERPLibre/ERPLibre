#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Rapatrie le moteur Set-OPS par Google Repo, à la révision épinglée dans
# manifest/git_manifest_setops.xml. Geste SUR DEMANDE : aucune autre
# installation ne contacte la forge du moteur. Se lance depuis la racine
# d'ERPLibre, comme les autres scripts de script/manifest/ :
#
#   ./script/manifest/update_manifest_local_setops.sh
#
# Trois gardes passent AVANT tout effet de bord — démon git, fusion,
# .repo/ — et toutes parlent avant que le script ne sorte : repo absent ou
# non exécutable, chemin du moteur occupé par un dossier que repo n'a pas
# posé, HEAD détaché qu'aucune branche ne contient. Elles ne font que lire :
# un refus ne laisse rien derrière lui.
#
# La garde du chemin tourne dans .venv.erplibre/bin/python : absent ou non
# exécutable, elle refuse en disant que l'emplacement n'a pas pu être
# vérifié, sans nommer ce qui l'occupe.
#
# Code de sortie : 3 quand un dossier que repo n'a pas posé occupe le
# chemin du moteur, 2 sans déclaration lisible du moteur, 1 pour les autres
# refus ; les gardes passées, celui de la fusion, de « repo init » ou de
# « repo sync », le premier qui échoue.

. ./env_var.sh || exit 1

# Verbosité de l'installation (git-repo). Silencieuse par défaut ;
# EL_VERBOSE=1 rétablit les logs détaillés (repo sync, git daemon).
if [ "${EL_VERBOSE:-0}" = "1" ]; then
  REPO_VERBOSE="-v"; DAEMON_VERBOSE="--verbose"
else
  REPO_VERBOSE="-q"; DAEMON_VERBOSE=""
fi

# Chaque garde note son refus sans sortir ; le code du module l'emporte
# quand plusieurs refusent.
RC_GARDES=0

# Garde 1 : Google Repo installé.
if [ ! -x .venv.erplibre/bin/repo ]; then
  echo "Erreur : .venv.erplibre/bin/repo absent ou non exécutable." >&2
  echo "  L'installer d'abord : ./script/install/install_git_repo.sh" >&2
  RC_GARDES=1
fi

# Garde 2 : le chemin du moteur est libre, ou repo y a posé l'arbre. Un
# clone manuel l'occupe-t-il, « repo sync » refuserait d'y poser le projet,
# ou extrairait sa révision par-dessus : le module le dit (code 3) et nomme
# la commande qui le met de côté. Le chemin se lit dans le manifeste,
# jamais recopié ici.
if [ -x .venv.erplibre/bin/python ]; then
  .venv.erplibre/bin/python -m script.setops.engine verifier-emplacement || RC_GARDES=$?
else
  echo "Erreur : .venv.erplibre/bin/python absent ou non exécutable." >&2
  echo "  L'emplacement du moteur n'a pas pu être vérifié." >&2
  echo "  Lancer l'installation d'ERPLibre d'abord." >&2
  [ "${RC_GARDES}" -ne 0 ] || RC_GARDES=1
fi

# Garde 3 : la révision du manifeste est un NOM DE BRANCHE, jamais un SHA
# nu — « repo init -b <sha> » échoue sur un espace de travail neuf (voir
# update_manifest_local_dev.sh).
MANIFEST_REV=$(git symbolic-ref --quiet --short HEAD || true)
if [ -z "${MANIFEST_REV}" ]; then
  # HEAD détaché : une branche qui contient ce commit.
  MANIFEST_REV=$(git branch --contains HEAD --format='%(refname:short)' 2>/dev/null | grep -v '[()]' | head -1)
fi
if [ -z "${MANIFEST_REV}" ]; then
  echo "Erreur : impossible de déterminer une branche pour repo init." >&2
  echo "  HEAD est détaché et aucune branche ne contient ce commit." >&2
  [ "${RC_GARDES}" -ne 0 ] || RC_GARDES=1
fi

[ "${RC_GARDES}" -eq 0 ] || exit "${RC_GARDES}"
SETOPS_PATH=$(.venv.erplibre/bin/python -m script.setops.engine chemin) || exit $?

# Démon git local servant ce dépôt en git://127.0.0.1:9418, qui écoute la
# boucle locale seulement (voir update_manifest_local_dev.sh). Un démon
# laissé par une exécution interrompue garde le port : il est arrêté
# d'abord.
if pkill -f "daemon --base-path=. --export-all" 2>/dev/null; then
  sleep 1  # le noyau libère le port 9418 avant qu'on le reprenne
fi

git daemon --base-path=. --export-all --listen=127.0.0.1 --reuseaddr --informative-errors ${DAEMON_VERBOSE} &
DAEMON_PID=$!
# Le démon lancé ici s'arrête quoi qu'il arrive, sans jamais faire échouer
# le script s'il est déjà parti. Le code de sortie reste celui passé à exit.
trap 'kill "${DAEMON_PID}" 2>/dev/null || true' EXIT

if [ -L "$EL_MANIFEST_DEV" ]; then
  MANIFEST_TARGET=$(readlink -f "$EL_MANIFEST_DEV")
else
  MANIFEST_TARGET="$EL_MANIFEST_DEV"
fi

if command -v nproc >/dev/null 2>&1; then
  JOBS="$(nproc --all)"
else
  JOBS="$(sysctl -n hw.ncpu)"
fi

# Manifeste local : celui du script de développement, plus le moteur. Une
# fois le moteur géré par repo, les fusions suivantes le reprennent d'elles-
# mêmes (git_merge_repo_manifest.py lit .repo/project.list).
.venv.erplibre/bin/python ./script/git/git_merge_repo_manifest.py --output .repo/local_manifests/erplibre_manifest.xml --with_OCA --with_setops || exit $?

.venv.erplibre/bin/repo init -u git://127.0.0.1:9418/ -b "${MANIFEST_REV}" -m ${MANIFEST_TARGET} "$@" || exit $?

# Seul le moteur est rapatrié et extrait. Mais repo aligne
# .repo/project.list sur le manifeste fraîchement fusionné, comme le ferait
# le script de développement : un projet que ce manifeste ne nomme plus
# perd son arbre s'il est propre (ses objets restent sous .repo/projects/),
# et fait échouer le sync, en le nommant, s'il porte des modifications.
.venv.erplibre/bin/repo sync -c -j "$JOBS" ${REPO_VERBOSE} -m ${MANIFEST_TARGET} "${SETOPS_PATH}"
exit $?
