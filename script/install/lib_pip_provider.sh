#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque SOURÇABLE : installer des paquets Python dans un venv donné.
#
# Seul endroit du dépôt qui décide COMMENT les paquets sont posés. Deux
# fournisseurs, même contrat de sortie :
#   pip  historique, toujours présent dans un venv.
#   uv   nettement plus rapide sur la résolution, le téléchargement et la
#        pose ; il met aussi en cache les roues qu'il CONSTRUIT, ce qui
#        compte là où rien n'a de roue publiée.
#
# EL_PIP_PROVIDER choisit : auto (défaut), uv, ou pip.
#
# CE QUE ÇA NE FAIT PAS — et il faut le savoir avant d'en attendre trop :
# « poetry install --no-root » n'est PAS concerné. uv ne lit pas poetry.lock
# (astral-sh/uv#1804, fermé « not planned ») et Poetry 2.1.3 n'a plus la
# commande « export ». Or c'est cette étape qui domine : 354 paquets contre
# 153 pour le venv d'outils. Le gain porte donc sur le venv d'outils et
# l'amorçage de Poetry, pas sur le gros morceau.
#
# Et sur s390x il est quasi nul : une trentaine de paquets binaires n'ont
# aucune roue (numpy, pandas, pillow, lxml, pymupdf…) et se COMPILENT. uv
# n'enlève pas une seconde de gcc ; il parallélise seulement entre paquets.

# uv ne supporte pas officiellement Python 3.7, encore utilisé par Odoo 12
# et 13. En dessous de ce seuil on reste sur pip, sans discuter.
EL_UV_MIN_PY_MINOR=8

el_uv_usable() {
  # $1 = interpréteur du venv visé.
  local py="$1" minor
  command -v uv > /dev/null 2>&1 || return 1
  [ -x "${py}" ] || return 1
  minor="$("${py}" -c 'import sys;print(sys.version_info[1])' 2> /dev/null)"
  [ -n "${minor}" ] || return 1
  [ "${minor}" -ge "${EL_UV_MIN_PY_MINOR}" ] 2> /dev/null || return 1
}

# API publique : installe dans le venv `$1`, avec les arguments qui suivent.
#
# La CIBLE est toujours explicite, jamais déduite de l'environnement. uv
# cherche sinon un « .venv » dans le répertoire courant ou un parent, et
# poetry.toml en déclare justement un — le dépôt porte déjà la trace de cette
# confusion, des dépendances du pyproject Odoo s'étant retrouvées dans
# .venv.erplibre. « --python » ferme la question.
#
# « uv pip sync » n'est jamais utilisé : il SUPPRIME ce qui n'est pas dans le
# fichier d'entrée, donc pip lui-même et tout ce que Poetry a posé.
el_pip_install() {
  local venv="$1"
  shift
  local py="${venv}/bin/python"
  local provider="${EL_PIP_PROVIDER:-auto}"

  if [ "${provider}" != "pip" ] && el_uv_usable "${py}"; then
    echo "  installation par uv ($(uv --version 2>&1 | head -1))"
    if uv pip install --python "${py}" "$@"; then
      return 0
    fi
    if [ "${provider}" = "uv" ]; then
      return 1
    fi
    # uv est plus strict que pip sur les métadonnées : il refuse des paquets
    # que pip accepte. Le repli n'est donc pas théorique.
    echo "  uv a echoue : reprise avec pip." >&2
  fi
  "${py}" -m pip install "$@"
}
