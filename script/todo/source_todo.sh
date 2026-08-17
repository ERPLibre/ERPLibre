#!/bin/bash
DIR_VENV_ERPLIBRE_EXIST=1
DIR_VENV_ERPLIBRE=".venv.erplibre"
# If not exist, create it and do installation
# Can be in conflict with ./script/install_locally.sh

if [[ ! -d "$DIR_VENV_ERPLIBRE" ]]; then
  DIR_VENV_ERPLIBRE_EXIST=0
  echo "$DIR_VENV_ERPLIBRE does not exist."
  # Le test d'origine etait inoperant : le tilde entre guillemets n'est pas
  # etendu, et « -d » testait un FICHIER comme un repertoire. La condition
  # etait donc toujours vraie, la commande echouait en « No such file or
  # directory », et le repli « python -m venv » ne servait jamais.
  # shellcheck source=script/install/lib_python_provider.sh
  . ./script/install/lib_python_provider.sh
  EL_PY_WANT="$(< ./conf/python-erplibre-version)"
  # Ici on ne PROVISIONNE pas : ce script s'execute au demarrage de TODO, il
  # doit rester rapide et hors reseau. On prend ce qui est deja pose, sinon
  # le python du systeme.
  EL_PY_EXEC="$(el_pyenv_exec_path "${EL_PY_WANT}")"
  el_python_is_version "${EL_PY_EXEC}" "${EL_PY_WANT}" \
    || EL_PY_EXEC="$(el_mise_exec_path "${EL_PY_WANT}" 2> /dev/null)"
  if [[ -n "${EL_PY_EXEC}" ]] && [[ -x "${EL_PY_EXEC}" ]]; then
    "${EL_PY_EXEC}" -m venv $DIR_VENV_ERPLIBRE
  else
    python3 -m venv $DIR_VENV_ERPLIBRE
  fi
fi

# If exist, source it and start installation
source ./.venv.erplibre/bin/activate
if [[ $DIR_VENV_ERPLIBRE_EXIST -eq 0 ]]; then
  pip install -r requirement/erplibre_require-ments.txt
fi

./script/todo/todo.py
