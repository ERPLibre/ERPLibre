#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque SOURÇABLE : « une version de Python » -> « un interpréteur ».
#
# C'est le seul endroit du dépôt qui décide COMMENT un interpréteur est
# obtenu. Tout le reste ne consomme que des chemins de venv, jamais pyenv ni
# mise. Ajouter un fournisseur se fait donc ici, et nulle part ailleurs.
#
# Deux fournisseurs :
#   pyenv  historique. Compile CPython depuis les sources : 1 à 3 min sur une
#          machine récente, bien plus sous émulation, et il lui faut une
#          douzaine de -dev (openssl, zlib, readline, sqlite, bzip2, xz, tk…).
#   mise   pose un CPython PRÉCOMPILÉ (astral python-build-standalone) :
#          quelques secondes, aucun compilateur requis.
#
# EL_PYTHON_PROVIDER choisit : auto (défaut), mise, ou pyenv.
#
# En mode « auto », un interpréteur DÉJÀ présent gagne, quel que soit le
# fournisseur qui l'a posé. Une installation pyenv qui marche n'est donc
# jamais doublée par un second CPython de 150 Mo.

# Ne jamais laisser mise compiler en silence : sans build précompilée pour la
# plateforme, il retomberait sur python-build — le moteur de pyenv — et on
# aurait la lenteur de pyenv sans son outillage. « false » = télécharger ou
# échouer ; l'échec nous fait basculer proprement sur le repli.
export MISE_PYTHON_COMPILE=false

el_pyenv_root() {
  echo "${PYENV_ROOT:-${HOME}/.pyenv}"
}

# Chemin de l'interpréteur pyenv d'une version, qu'il existe ou non.
el_pyenv_exec_path() {
  echo "$(el_pyenv_root)/versions/$1/bin/python"
}

# Interpréteur déjà posé par mise, sans le moindre accès réseau.
el_mise_exec_path() {
  command -v mise > /dev/null 2>&1 || return 1
  local out
  out="$(mise where "python@$1" 2> /dev/null)" || return 1
  [ -n "${out}" ] && [ -x "${out}/bin/python" ] || return 1
  echo "${out}/bin/python"
}

# Vrai si l'exécutable rend EXACTEMENT la version demandée. Un interpréteur
# présent mais d'une autre version casserait Poetry, dont le pyproject exige
# le patch au près (>=3.12.10,<3.13).
el_python_is_version() {
  local exe="$1" want="$2" got
  [ -x "${exe}" ] || return 1
  got="$("${exe}" -c 'import platform;print(platform.python_version())' 2> /dev/null)"
  [ "${got}" = "${want}" ]
}

# Vrai si l'exécutable CONVIENT : même majeure.mineure, et patch au moins
# égal au demandé. C'est exactement ce qu'exige le pyproject — « >=3.12.10,
# <3.13 » — et non l'égalité stricte que testait el_python_is_version.
#
# La distinction n'est pas théorique. Tumbleweed s390x livre python312 en
# 3.12.13 : parfaitement utilisable, mais rejeté par l'égalité, ce qui forçait
# pyenv à COMPILER CPython — et gcc 15.2 s'y arrête sur une erreur interne
# dans Parser/parser.c, un fichier généré de quarante mille lignes.
el_python_is_compatible() {
  local exe="$1" want="$2" got
  [ -x "${exe}" ] || return 1
  got="$("${exe}" -c 'import platform;print(platform.python_version())' \
    2> /dev/null)"
  [ -n "${got}" ] || return 1
  # Même majeure.mineure : 3.13 ne convient pas à un pyproject borné à <3.13.
  [ "${got%.*}" = "${want%.*}" ] || return 1
  # Patch au moins égal, comparé en version et non en chaîne (3.12.9 < 3.12.10).
  [ "$(printf '%s\n%s\n' "${want}" "${got}" | sort -V | head -1)" = "${want}" ]
}

# Interpréteur de la DISTRIBUTION qui conviendrait, s'il y en a un.
#
# Cherché avant toute compilation : sur une architecture émulée, bâtir CPython
# prend des dizaines de minutes quand il aboutit. Le nom suit la convention de
# toutes les distributions, « python3.12 ».
el_distro_python_exec() {
  local want="$1" exe
  # Des chemins SYSTEME, jamais « command -v » : dans un venv activé celui-ci
  # rend le python DU VENV, et l'on bâtirait un venv depuis un venv. Le PATH
  # d'une session interactive n'a rien à faire dans cette décision.
  for exe in "/usr/bin/python${want%.*}" "/usr/local/bin/python${want%.*}"; do
    if el_python_is_compatible "${exe}" "${want}"; then
      echo "${exe}"
      return 0
    fi
  done
  return 1
}

# Installe la version via mise. Renvoie le chemin, ou échoue.
el_mise_install() {
  local version="$1" exe
  command -v mise > /dev/null 2>&1 || return 1
  echo "---- Python ${version} via mise (precompile) ----" >&2
  mise install "python@${version}" >&2 || return 1
  exe="$(el_mise_exec_path "${version}")" || return 1
  el_python_is_version "${exe}" "${version}" || return 1
  echo "${exe}"
}

# Installe la version via pyenv, en posant pyenv lui-même au besoin.
el_pyenv_install() {
  local version="$1" root exe
  root="$(el_pyenv_root)"
  exe="$(el_pyenv_exec_path "${version}")"
  if [[ ! -d "${root}" ]]; then
    echo "---- Installation de pyenv dans ${root} ----" >&2
    curl -L https://raw.githubusercontent.com/pyenv/pyenv-installer/master/bin/pyenv-installer \
      | bash >&2 || return 1
  fi
  export PATH="${root}/bin:$PATH"
  eval "$(pyenv init - 2> /dev/null)" || true
  eval "$(pyenv virtualenv-init - 2> /dev/null)" || true
  if [[ ! -d "${root}/versions/${version}" ]]; then
    # pyenv COMPILE CPython : sans compilateur C, il télécharge l'archive,
    # lance configure et s'arrête sur « no acceptable C compiler found », après
    # avoir gaspillé le téléchargement. On le dit AVANT, et on nomme le paquet.
    if ! command -v cc > /dev/null 2>&1 \
      && ! command -v gcc > /dev/null 2>&1; then
      echo "Aucun compilateur C : pyenv ne peut pas compiler Python." >&2
      echo "  Installez le necessaire de compilation (build-essential," >&2
      echo "  gcc/gcc-c++, ou le motif devel_basis) puis relancez." >&2
      return 1
    fi
    echo "---- Python ${version} via pyenv (compilation) ----" >&2
    # La liste des versions connues vient du dépôt git de pyenv : sans ce
    # « pull », une version récente est « not a known version ».
    (cd "${root}" && git pull) >&2 || true
    # Le contrôle d'erreur d'origine testait un $retVal jamais affecté ici :
    # un échec de compilation passait inaperçu jusqu'au test d'existence.
    if ! yes n | pyenv install "${version}" >&2; then
      echo "pyenv install ${version} a echoue." >&2
      return 1
    fi
  fi
  el_python_is_version "${exe}" "${version}" || return 1
  echo "${exe}"
}

# API publique : imprime le chemin absolu d'un interpréteur de cette version,
# ou rien (et rend non nul) si aucun fournisseur n'y parvient.
el_python_exec() {
  local version="$1" provider="${EL_PYTHON_PROVIDER:-auto}" exe

  # 1) Déjà présent ? On ne réinstalle rien et on ne touche pas au réseau.
  #    C'est ce qui rend le changement sans effet pour une installation
  #    pyenv existante.
  if [ "${provider}" != "mise" ]; then
    exe="$(el_pyenv_exec_path "${version}")"
    if el_python_is_version "${exe}" "${version}"; then
      echo "${exe}"
      return 0
    fi
  fi
  if [ "${provider}" != "pyenv" ]; then
    if exe="$(el_mise_exec_path "${version}")" \
      && el_python_is_version "${exe}" "${version}"; then
      echo "${exe}"
      return 0
    fi
  fi

  # 2) Un interpréteur de la DISTRIBUTION qui convient ? Rien à installer,
  #    rien à compiler. Vérifié avant mise et pyenv : c'est le seul chemin
  #    qui ne coûte rien, et sur s390x le seul qui aboutisse partout — mise
  #    n'y publie aucun binaire, et pyenv doit compiler.
  #    Uniquement en mode « auto » : demander mise ou pyenv explicitement doit
  #    être respecté, sinon le réglage ne veut plus rien dire.
  if [ "${provider}" = "auto" ] \
    && exe="$(el_distro_python_exec "${version}")"; then
    echo "Python $("${exe}" -V 2>&1 | awk '{print $2}') de la distribution :" \
      "aucune compilation." >&2
    echo "${exe}"
    return 0
  fi

  # 3) Rien de posé : il faut provisionner. mise d'abord quand il est là,
  #    parce qu'il télécharge au lieu de compiler.
  if [ "${provider}" != "pyenv" ]; then
    if exe="$(el_mise_install "${version}")"; then
      echo "${exe}"
      return 0
    fi
    [ "${provider}" = "mise" ] && return 1
    command -v mise > /dev/null 2>&1 \
      && echo "mise n'a pas pu fournir Python ${version} : repli sur pyenv." >&2
  fi
  el_pyenv_install "${version}"
}
