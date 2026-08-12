. ./env_var.sh
EL_USER=${USER}
EL_HOME=$PWD
EL_HOME_ODOO="${EL_HOME}/odoo${EL_ODOO_VERSION}/odoo"
#EL_INSTALL_WKHTMLTOPDF="True"
#EL_PORT="8069"
#EL_LONGPOLLING_PORT="8072"
#EL_SUPERADMIN="admin"
#EL_CONFIG_FILE="${EL_HOME}/config.conf"
#EL_CONFIG="${EL_USER}"
#EL_MINIMAL_ADDONS="False"
#EL_INSTALL_NGINX="True"
FILE_INSTALLATION_VERSION=".repo/installed_odoo_version.txt"

Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

# example, 3.7.8 will be 3.7 into PYTHON_VERSION_MAJOR
PYTHON_VERSION_MAJOR=$(echo "$EL_PYTHON_ODOO_VERSION" | sed 's/\.[^\.]*$//')
VENV_ERPLIBRE_PATH=$(cat "conf/python-erplibre-venv" | xargs)
VENV_ODOO_PATH=".venv.${EL_ERPLIBRE_VERSION}"
POETRY_ODOO_PATH=${VENV_ERPLIBRE_PATH}/bin/poetry
export WITH_POETRY_INSTALLATION=1

# Verbosité de l'installation Poetry : silencieuse (-q) par défaut, les logs
# détaillés (-vvv) reviennent avec la variable d'environnement EL_VERBOSE=1.
if [[ "${EL_VERBOSE:-0}" == "1" ]]; then
    POETRY_VERBOSE="-vvv"
else
    POETRY_VERBOSE="-q"
fi

# EL_PHASE controls which steps to execute.  Used by install_locally_dev.sh
# for parallel installation — do not set manually unless you know what you do.
#   all    (default) – full install: setup + poetry phases
#   setup             – prereqs only: venvs, pip-erplibre, git-repo
#   poetry            – python packages: poetry install + post-install
EL_PHASE=${EL_PHASE:-all}

# ── Setup phase (venvs + pip-erplibre + git-repo) ────────────────────────────
if [[ "${EL_PHASE}" != "poetry" ]]; then
    ./script/generate_config.sh

    # Generate empty addons if missing
    path_addons_addons="./odoo${EL_ODOO_VERSION}/addons/addons"
    if [[ ! -d "${path_addons_addons}" ]]; then
        mkdir -p "${path_addons_addons}"
    fi

    if [[ ! -n "${DOCKER_BUILD}" ]]; then
        # Install ERPLibre venv
        echo -e "Install ${VENV_ERPLIBRE_PATH} with ${EL_PYTHON_ERPLIBRE_VERSION}"
        # Le code de retour n'était PAS regardé : quand l'interpréteur ne
        # pouvait pas être obtenu, le script continuait, et tout ce qui suit
        # échouait à son tour sur un venv inexistant. Le log devenait une
        # cascade de « No such file or directory » répartie sur trois fichiers,
        # où la cause réelle — pas de compilateur C — se perdait tout en haut.
        if ! ./script/install/install_venv.sh "ERPLibre" "${VENV_ERPLIBRE_PATH}" "${EL_PYTHON_ERPLIBRE_VERSION}"; then
            echo "Echec de creation de ${VENV_ERPLIBRE_PATH}, arret."
            exit 1
        fi
        # Install Odoo venv
        echo -e "Install ${VENV_ODOO_PATH} with ${EL_PYTHON_ODOO_VERSION}"
        if ! ./script/install/install_venv.sh "Odoo" "${VENV_ODOO_PATH}" "${EL_PYTHON_ODOO_VERSION}"; then
            echo "Echec de creation de ${VENV_ODOO_PATH}, arret."
            exit 1
        fi
    else
        mkdir .venv
    fi

    source ./${VENV_ERPLIBRE_PATH}/bin/activate
    echo -e "Upgrade pip to ${VENV_ERPLIBRE_PATH}"
    pip install --upgrade pip
    pip install -r requirement/erplibre_require-ments.txt

    ./script/install/install_git_repo.sh
fi

# ── Poetry phase (install python packages + post-install) ────────────────────
if [[ "${EL_PHASE}" != "setup" ]]; then
    source ${VENV_ODOO_PATH}/bin/activate
    echo -e "Upgrade pip to ${VENV_ODOO_PATH}"
    pip install --upgrade pip

    echo -e "\n---- Installing poetry dependency ----"

    if [[ -z "${EL_POETRY_VERSION}" ]]; then
        echo -e "${Red}Error${Color_Off} missing poetry version, please check file .poetry-version"
        cat .poetry-version
        ls -la
        exit 1
    fi

    # s390x UNIQUEMENT — la borne ci-dessous ne doit toucher aucune autre
    # architecture, et le test d'architecture vient donc en premier.
    #
    # Poetry tire keyring, donc SecretStorage, donc cryptography, dont la
    # DERNIÈRE version : rien ne la borne à cette étape. Partout ailleurs c'est
    # sans conséquence, pip y pose une roue manylinux qui embarque son propre
    # OpenSSL en statique — vérifié, la 50.0.0 en publie pour x86_64, aarch64,
    # ppc64le et armv7l. s390x est la SEULE sans roue : elle compile, contre
    # l'OpenSSL du système.
    #
    # Or cryptography 47 a retiré le support d'OpenSSL 1.1.1 — vérifié version
    # par version, les gardes « CRYPTOGRAPHY_OPENSSL_300_OR_GREATER » de
    # fips.rs disparaissent entre la 46 et la 47 — et Ubuntu 20.04 livre
    # 1.1.1f. D'où « EVP_default_properties_is_fips_enabled not found in ffi ».
    # Sur s390x en 22.04 et au-delà, OpenSSL est en 3.x : aucune borne.
    PIP_CONSTRAINT_CRYPTO=""
    if [[ "$(uname -m)" == "s390x" ]]; then
        OPENSSL_VER="$(pkg-config --modversion openssl 2>/dev/null \
            || openssl version 2>/dev/null | awk '{print $2}')"
        case "${OPENSSL_VER}" in
            3.* | 4.*) ;;
            "") echo "s390x : version d'OpenSSL indeterminee, aucune borne." ;;
            *)
                echo "s390x, OpenSSL ${OPENSSL_VER} < 3 : cryptography borne a <47 pour poetry."
                PIP_CONSTRAINT_CRYPTO="cryptography<47"
                ;;
        esac
    fi

    # Delete artifacts created by pip, cause error in next "poetry install"
    if [[ ! -f "${POETRY_ODOO_PATH}" ]]; then
        echo -e "Install Poetry ${POETRY_ODOO_PATH}"
        pip install ${PIP_CONSTRAINT_CRYPTO} poetry==${EL_POETRY_VERSION}
        poetry --version
        # Fix broken poetry by installing ignored dependence
        #    poetry lock --no-update
        # To fix keyring problem when installation is blocked, use
        export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
        if [[ ${WITH_POETRY_INSTALLATION} -ne 0 ]]; then
            poetry install --no-root ${POETRY_VERBOSE}
        fi
        retVal=$?
        if [[ $retVal -ne 0 ]]; then
            echo "Poetry installation error with status ${retVal}"
            # « -q » masque la CAUSE. On rejoue en « -vvv » (debug) car c'est
            # le SEUL niveau où Poetry affiche la sortie des sous-processus
            # (git clone/checkout, build pip) — donc l'erreur réelle d'une
            # dépendance VCS/build. Capturé dans le log pour diagnostic.
            echo "---- Poetry: rejeu -vvv pour diagnostic ----"
            poetry install --no-root -vvv 2>&1 || true
            exit 1
        fi
    fi

    # Delete artifacts created by pip, cause error in next "poetry install"
    rm -rf artifacts

    # Link for dev tools into Odoo
    echo -e "\n---- Add link dependency in site-packages of Python ----"
    # TODO this link can break, the symbolic link is maybe not created
    ln -fs "${EL_HOME_ODOO}/odoo" "${EL_HOME}/${VENV_ODOO_PATH}/lib/python${PYTHON_VERSION_MAJOR}/site-packages/"

    # Force to return to erplibre source
    source ./${VENV_ERPLIBRE_PATH}/bin/activate

    # Add trace of installation
    LINE_TO_ADD="odoo${EL_ODOO_VERSION}"
    mkdir -p "$(dirname "$FILE_INSTALLATION_VERSION")"
    touch "$FILE_INSTALLATION_VERSION"
    if ! grep -qxF "$LINE_TO_ADD" "$FILE_INSTALLATION_VERSION"; then
        echo "$LINE_TO_ADD" >> "$FILE_INSTALLATION_VERSION"
    fi
fi
