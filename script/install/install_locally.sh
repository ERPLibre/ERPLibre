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
# Poetry est installé dans le venv ODOO, pas dans celui des outils : le garde
# d'idempotence visait le mauvais chemin, donc il était TOUJOURS vrai. Sans
# conséquence visible — poetry se réinstallait pour rien — mais le jour où ce
# fichier aurait existé, « poetry install » aurait été purement sauté.
POETRY_ODOO_PATH=${VENV_ODOO_PATH}/bin/poetry

# Choix pip/uv : un seul endroit décide, comme pour mise/pyenv.
# shellcheck source=script/install/lib_pip_provider.sh
. ./script/install/lib_pip_provider.sh
# Bornage des compilations : voir el_build_limit_jobs.
. ./script/install/lib_lowmem.sh
export WITH_POETRY_INSTALLATION=1

# Verbosité de l'installation Poetry. « -q » a été retiré du défaut : dans Cleo,
# le mode silencieux coupe AUSSI la sortie d'erreur. Mesuré — « poetry -q
# commande-inexistante » rend 1 sans imprimer un caractère, quand la même sans
# « -q » nomme le problème. Un échec devenait donc parfaitement muet, et c'est
# pour cela qu'il avait fallu ajouter un rejeu de diagnostic plus bas.
# La verbosité par défaut de Poetry tient en une ligne par paquet.
if [[ "${EL_VERBOSE:-0}" == "1" ]]; then
    POETRY_VERBOSE="-vvv"
else
    POETRY_VERBOSE=""
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
    el_pip_install "${VENV_ERPLIBRE_PATH}" \
      -r requirement/erplibre_require-ments.txt

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

    # Le garde ne couvre QUE l'amorçage de Poetry. « poetry install » doit
    # rejouer à chaque fois : c'est lui qui applique un lock régénéré par
    # « make poetry_update ». L'englober rendrait la mise à jour sans effet
    # dès la seconde installation.
    if [[ ! -x "${POETRY_ODOO_PATH}" ]]; then
        echo -e "Install Poetry ${POETRY_ODOO_PATH}"
        el_pip_install "${VENV_ODOO_PATH}" \
          ${PIP_CONSTRAINT_CRYPTO} "poetry==${EL_POETRY_VERSION}"
    fi
    # Chemin EXPLICITE, jamais le « poetry » du PATH. Le script active pourtant
    # le bon venv juste avant, mais poetry.toml porte « virtualenvs.create =
    # false » : hors activation, Poetry installe dans l'interpréteur de BASE.
    # Vérifié à la dure sur une VM — 772 paquets posés dans le CPython de mise,
    # invisibles du venv qui a « include-system-site-packages = false », et
    # promis à polluer tout autre venv bâti sur le même interpréteur.
    if [[ ! -x "${POETRY_ODOO_PATH}" ]]; then
        echo "Poetry introuvable a ${POETRY_ODOO_PATH}, arret."
        exit 1
    fi
    # Là où rien n'a de roue, « poetry install » COMPILE des centaines de
    # paquets, et le moteur de build de chacun lance nproc tâches en
    # parallèle. cc1plus demande jusqu'à 2,5 Gio pour un seul fichier de
    # matplotlib : six cœurs épuisent 8 Gio, et le noyau tue le compilateur
    # sans jamais nommer la mémoire. On borne d'après la mémoire disponible.
    if [[ "$(uname -m)" == "s390x" ]]; then
        el_build_limit_jobs
    fi
    "${POETRY_ODOO_PATH}" --version
    # To fix keyring problem when installation is blocked, use
    export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
    # « poetry install » reste à Poetry : uv ne lit pas poetry.lock
    # (astral-sh/uv#1804, « not planned ») et Poetry 2.1.3 n'a plus « export ».
    if [[ ${WITH_POETRY_INSTALLATION} -ne 0 ]]; then
        "${POETRY_ODOO_PATH}" install --no-root ${POETRY_VERBOSE}
        retVal=$?
        if [[ $retVal -ne 0 ]]; then
            echo "Poetry installation error with status ${retVal}"
            # Un rejeu, parce qu'une partie des échecs sont des aléas de
            # téléchargement : le lock est figé, rien ne dépend de l'instant.
            # « -vvv » est le SEUL niveau où Poetry montre la sortie des
            # sous-processus (git clone, build pip), donc l'erreur réelle.
            #
            # Le « exit 1 » était INCONDITIONNEL : un rejeu réussi laissait une
            # installation complète... et la déclarait quand même en échec.
            # C'est ce qui a arrêté openSUSE Leap 16 sur un pdfminer-six posé
            # correctement au second essai.
            echo "---- Poetry: rejeu -vvv (diagnostic et seconde chance) ----"
            if "${POETRY_ODOO_PATH}" install --no-root -vvv 2>&1; then
                echo "Le rejeu a REUSSI : le premier echec etait transitoire."
            else
                exit 1
            fi
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
