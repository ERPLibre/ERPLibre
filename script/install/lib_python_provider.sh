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
#          quelques secondes, aucun compilateur requis. Seulement à partir
#          de 3.8 : en deçà, pyenv est le seul fournisseur.
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

# Chemin du binaire mise, même hors du PATH, ou échec.
#
# L'installateur de mise.run le dépose dans ~/.local/bin (MISE_INSTALL_PATH
# le déplace), répertoire qu'un script ne trouve pas toujours dans son PATH,
# ni la session qui vient de le poser. Le chercher là aussi permet à
# l'installation de continuer avec mise sans que personne ait à toucher au
# PATH, et au venv suivant de le retrouver dans un autre processus.
el_mise_cmd() {
  local exe
  if exe="$(command -v mise 2> /dev/null)"; then
    echo "${exe}"
    return 0
  fi
  exe="${MISE_INSTALL_PATH:-${HOME}/.local/bin/mise}"
  [ -x "${exe}" ] || return 1
  echo "${exe}"
}

# Interpréteur déjà posé par mise, sans le moindre accès réseau.
el_mise_exec_path() {
  local mise out
  mise="$(el_mise_cmd)" || return 1
  out="$("${mise}" where "python@$1" 2> /dev/null)" || return 1
  [ -n "${out}" ] && [ -x "${out}/bin/python" ] || return 1
  echo "${out}/bin/python"
}

# Vrai si mise peut POSER cette version sans la compiler. Ses CPython
# précompilés viennent de python-build-standalone, qui commence à la série
# 3.8 : pour 2.x et 3.0 à 3.7, MISE_PYTHON_COMPILE=false le fait échouer, et
# seul pyenv fournit la version. Lancé à la main, sans cette variable, mise la
# compilerait lui-même, sans les drapeaux qu'el_pyenv_install ajoute pour 2.7 :
# rien ne doit donc proposer, appeler ni conseiller mise pour ces versions.
el_mise_a_precompile() {
  case "$1" in
    [0-2] | [0-2].* | 3.[0-7] | 3.[0-7].*) return 1 ;;
  esac
  return 0
}

# Peut-on poser une question ? Il faut stdin pour lire la réponse et stderr
# pour la montrer. PAS stdout : el_python_exec est lu par substitution de
# commande, où stdout est un tube même devant un terminal. Un déploiement de
# VM, un build Docker ou une CI n'ont pas de terminal, et n'attendent donc
# jamais une réponse que personne ne donnera.
#
# En mode non interactif (EL_NON_INTERACTIVE=1, voir lib_non_interactive.sh),
# jamais : chaque question prend son défaut sans attendre.
#
# Fonction isolée pour qu'un test puisse la remplacer sans pseudo-terminal.
el_peut_demander() {
  [ "${EL_NON_INTERACTIVE:-}" != "1" ] && [ -t 0 ] && [ -t 2 ]
}

# Vrai pour un oui explicite, en français ou en anglais. Les casses sont
# écrites à la main : « ${1,,} » exige bash 4, et macOS livre bash 3.2.
el_repond_oui() {
  case "$1" in
    o | O | oui | Oui | OUI | y | Y | yes | Yes | YES) return 0 ;;
  esac
  return 1
}

# Vrai pour un non explicite, en français ou en anglais.
el_repond_non() {
  case "$1" in
    n | N | non | Non | NON | no | No | NO) return 0 ;;
  esac
  return 1
}

# Pose une question oui/non sur stderr, lit la réponse sur stdin, et rend 0
# pour un oui. $2 donne le défaut d'une réponse vide (Entrée), « o » ou « n »
# (non si absent). $3 donne la réponse quand personne ne répond — fin de
# l'entrée, ou EL_QUESTION_DELAI secondes écoulées (60 par défaut) — et vaut
# $2 si absent. Chaque venv s'installe dans son propre processus : la
# question revient au suivant, et une installation laissée sans surveillance
# ne doit pas attendre une réponse que personne ne donnera. Avec le défaut
# non, seul un oui explicite rend 0 ; avec le défaut oui, seul un non rend 1.
el_demander() {
  local question="$1" defaut="${2:-n}" delai="${EL_QUESTION_DELAI:-60}"
  local muet="${3:-${2:-n}}" reponse="" choix="o/N" lettre="N" absent="N"
  [ "${defaut}" = "o" ] && choix="O/n" && lettre="O"
  [ "${muet}" = "o" ] && absent="O"
  if [ "${absent}" = "${lettre}" ]; then
    printf '%s (%s, defaut : %s dans %s s) ? ' "${question}" "${choix}" \
      "${lettre}" "${delai}" >&2
  else
    printf '%s (%s, sans reponse en %s s : %s) ? ' "${question}" \
      "${choix}" "${delai}" "${absent}" >&2
  fi
  if ! read -r -t "${delai}" reponse; then
    # Fin de l'entrée ou délai écoulé : finir la ligne de l'invite.
    echo >&2
    reponse="${muet}"
  fi
  [ -n "${reponse}" ] || reponse="${defaut}"
  if [ "${defaut}" = "o" ]; then
    ! el_repond_non "${reponse}"
  else
    el_repond_oui "${reponse}"
  fi
}

# Pose l'OUTIL mise. 0 s'il est utilisable ensuite, 2 sur une plateforme
# sans binaire publié, 1 pour tout autre échec. Tout part sur stderr :
# l'appelant peut être lu par substitution de commande.
#
# Téléchargé dans un fichier, PUIS exécuté, comme pyenv plus bas : quand
# curl alimente sh par un tube, le statut est celui de sh, qui rend 0 sur une
# entrée vide et masque un téléchargement raté.
el_mise_poser() {
  local mise installateur
  if mise="$(el_mise_cmd)"; then
    echo "mise deja present : $("${mise}" --version 2> /dev/null)" >&2
    return 0
  fi
  if command -v pacman > /dev/null 2>&1; then
    # En mode non interactif, sudo ne demande pas de mot de passe que
    # personne ne saisirait : sans ticket, il échoue aussitôt, et pyenv
    # reprend la main.
    if [ "${EL_NON_INTERACTIVE:-}" = "1" ]; then
      sudo -n pacman -S --needed --noconfirm mise >&2 || {
        echo "sudo demanderait un mot de passe : mise n'est pas pose." >&2
        return 1
      }
    else
      sudo pacman -S --needed --noconfirm mise >&2 || return 1
    fi
  elif [ "$(uname -m)" = "s390x" ]; then
    echo "mise ne publie pas de binaire s390x : on reste sur pyenv." >&2
    return 2
  else
    echo "Installation de mise depuis https://mise.run" >&2
    installateur="$(mktemp)" || return 1
    if ! curl -fsSL -o "${installateur}" https://mise.run; then
      rm -f "${installateur}"
      echo "Telechargement de l'installateur mise impossible" \
        "(reseau ou cache) : mise n'est pas pose." >&2
      return 1
    fi
    if ! sh "${installateur}" >&2; then
      rm -f "${installateur}"
      echo "L'installateur de mise a echoue (voir ci-dessus)." >&2
      return 1
    fi
    rm -f "${installateur}"
  fi
  if ! mise="$(el_mise_cmd)"; then
    echo "mise est pose, mais introuvable dans le PATH ni dans" \
      "${MISE_INSTALL_PATH:-${HOME}/.local/bin/mise}." >&2
    return 1
  fi
  echo "mise pose : ${mise}" >&2
}

# Le fichier de démarrage du shell de l'utilisateur, et le nom de ce shell
# pour « mise activate ». Rien pour un autre shell (fish, ksh…) : il ne lit
# ni l'un ni l'autre, et une ligne bash dans ~/.bashrc ne l'activerait pas.
# Un SHELL vide, ou sh, vaut bash : c'est le shell que l'installation lance.
el_mise_rc() {
  case "${SHELL##*/}" in
    zsh) echo "${ZDOTDIR:-${HOME}}/.zshrc zsh" ;;
    bash | sh | "") echo "${HOME}/.bashrc bash" ;;
    *) return 1 ;;
  esac
}

# Écrit l'activation de mise dans le fichier de démarrage du shell, une seule
# fois : un fichier qui l'active déjà n'est pas touché. Le chemin absolu de
# mise y figure, comme le suggère son installateur : la ligne fonctionne même
# quand ~/.local/bin n'est pas dans le PATH.
el_mise_rendre_permanent() {
  local mise rc shell active
  mise="$(el_mise_cmd)" || return 1
  read -r rc shell <<< "$(el_mise_rc)" || return 1
  [ -n "${rc}" ] || return 1
  # Une activation en commentaire ne compte pas : seule une ligne qui
  # s'exécute active mise.
  active='^[[:space:]]*[^#[:space:]][^#]*mise[^#]* activate'
  if [ -f "${rc}" ] && grep -Eq "${active}" "${rc}"; then
    echo "mise est deja active dans ${rc}." >&2
    return 0
  fi
  if ! printf '\n# mise, pose par ERPLibre\neval "$(%s activate %s)"\n' \
    "${mise}" "${shell}" >> "${rc}"; then
    echo "Ecriture impossible dans ${rc}." >&2
    return 1
  fi
  echo "mise active dans ${rc} : les nouveaux terminaux le trouvent." >&2
  echo "  Pour un terminal deja ouvert sous ce compte : source ${rc}" >&2
}

# Propose de rendre mise permanent, devant un terminal seulement ; sinon dit
# comment le faire. L'installation en cours n'en a pas besoin : el_mise_cmd
# retrouve mise sans le PATH.
el_mise_proposer_permanent() {
  local rc shell
  if ! read -r rc shell <<< "$(el_mise_rc)" || [ -z "${rc}" ]; then
    echo "Le shell ${SHELL##*/} n'est ni bash ni zsh : activez mise selon" >&2
    echo "  sa documentation (« $(el_mise_cmd) activate --help »)." >&2
    return 0
  fi
  if ! el_peut_demander; then
    echo "Pour activer mise dans vos terminaux : ajoutez a ${rc}" >&2
    echo "  eval \"\$($(el_mise_cmd) activate ${shell})\"" >&2
    return 0
  fi
  if el_demander "Activer mise de facon permanente dans ${rc}"; then
    el_mise_rendre_permanent
  else
    echo "${rc} n'est pas modifie." >&2
  fi
}

# Propose de poser mise juste avant que pyenv ne compile CPython. Rend 0 si
# mise vient d'être posé, 2 si la question a été posée et que la suite est
# pyenv — l'utilisateur sait déjà pourquoi —, 1 si rien n'a été demandé, 3
# si la réponse manque en mode non interactif : l'installation s'arrête.
#
# Rien n'est demandé quand mise est déjà là, sur s390x (aucun binaire), sans
# terminal, ni quand pyenv porte déjà la version : rien ne serait compilé.
# Rien non plus pour une version sans CPython précompilé : mise n'y gagnerait
# rien, et pyenv la compilerait quand même.
# Le défaut est oui, pour Entrée comme sans réponse au bout du délai : mise
# pose un CPython précompilé en quelques secondes, là où pyenv le compile et
# exige une douzaine de -dev. Le délai laisse le temps de refuser.
#
# En mode auto, un refus est retenu dans EL_MISE_REFUS, à la racine du
# dépôt : chaque venv
# s'installe dans son propre processus, et sans lui la question reviendrait
# au venv suivant, où le délai écoulé renverserait le « non ». Tant que le
# fichier existe, rien n'est plus demandé et pyenv compile ; « make
# install_mise » pose mise et l'efface.
#
# En mode non interactif (EL_NON_INTERACTIVE=1), rien n'est demandé non plus,
# mais rien n'est décidé à la place de l'utilisateur : EL_INSTALL_MISE=1 pose
# mise, EL_INSTALL_MISE=0 laisse pyenv compiler, et sans l'une ni l'autre
# l'installation s'arrête en les nommant.
# Relatif au dossier courant, la racine du dépôt ; une valeur déjà posée
# l'emporte.
EL_MISE_REFUS="${EL_MISE_REFUS:-.erplibre-mise-refus}"
el_mise_proposer() {
  local version="$1" provider="${EL_PYTHON_PROVIDER:-auto}" suite
  el_mise_a_precompile "${version}" || return 1
  el_mise_cmd > /dev/null && return 1
  [ "$(uname -m 2> /dev/null)" = "s390x" ] && return 1
  if [ "${provider}" != "mise" ] \
    && [ -d "$(el_pyenv_root)/versions/${version}" ]; then
    return 1
  fi
  if [ "${EL_NON_INTERACTIVE:-}" = "1" ]; then
    case "${EL_INSTALL_MISE:-}" in
      1)
        echo "mise est absent : EL_INSTALL_MISE=1, il est pose." >&2
        el_mise_poser && return 0
        echo "mise n'a pas pu etre pose." >&2
        return 2
        ;;
      0)
        echo "mise est absent, EL_INSTALL_MISE=0 : pyenv fournit Python" \
          "${version}." >&2
        return 2
        ;;
      *)
        echo "Mode non interactif : mise est absent, et rien ne dit s'il" >&2
        echo "  faut le poser pour fournir Python ${version}. Repondez par" >&2
        echo "  --mise yes|no, ou EL_INSTALL_MISE=1|0." >&2
        return 3
        ;;
    esac
  fi
  el_peut_demander || return 1
  # Ce qui suit un refus, dit tel quel : avec EL_PYTHON_PROVIDER=mise, il
  # n'y a pas de repli sur pyenv, et l'installation s'arrête.
  if [ "${provider}" = "mise" ]; then
    suite="l'installation s'arrete, EL_PYTHON_PROVIDER=mise exclut pyenv."
    echo "mise est absent, et EL_PYTHON_PROVIDER=mise n'autorise que lui" >&2
    echo "  pour fournir Python ${version}." >&2
  else
    suite="pyenv va compiler CPython ${version}."
    echo "mise est absent : sans lui, pyenv va COMPILER CPython ${version}" >&2
    echo "  -- quelques minutes, bien plus sous emulation, et une douzaine" >&2
    echo "  de -dev (openssl, zlib, readline, sqlite, bzip2, xz, tk). mise" >&2
    echo "  pose un CPython precompile en quelques secondes." >&2
  fi
  # Le refus retenu ne vaut qu'en mode auto : EL_PYTHON_PROVIDER=mise exige
  # mise, et la question y revient à chaque fois.
  if [ "${provider}" != "mise" ] && [ -e "${EL_MISE_REFUS}" ]; then
    echo "mise a ete refuse pour ce depot (${EL_MISE_REFUS}) : ${suite}" >&2
    echo "  « make install_mise » le pose et oublie ce refus." >&2
    return 2
  fi
  if ! el_demander "Installer mise maintenant" o; then
    echo "mise n'est pas pose : ${suite}" >&2
    if [ "${provider}" != "mise" ]; then
      : > "${EL_MISE_REFUS}"
      echo "  Refus retenu (${EL_MISE_REFUS}) : la question ne revient plus." >&2
    fi
    return 2
  fi
  if ! el_mise_poser; then
    echo "mise n'a pas pu etre pose : ${suite}" >&2
    return 2
  fi
  el_mise_proposer_permanent
  return 0
}

# Vrai si l'exécutable rend EXACTEMENT la version demandée. Un interpréteur
# présent mais d'une autre version casserait Poetry, dont le pyproject exige
# le patch au près (>=3.12.16,<3.13).
el_python_is_version() {
  local exe="$1" want="$2" got
  [ -x "${exe}" ] || return 1
  got="$("${exe}" -c 'import platform;print(platform.python_version())' 2> /dev/null)"
  [ "${got}" = "${want}" ]
}

# Vrai si l'exécutable CONVIENT. Deux exigences, selon ce qui borne l'appelant.
#
#   patch    même majeure.mineure, et patch au moins égal. C'est ce que le
#            pyproject d'Odoo demande — « >=3.12.16,<3.13 » —, et Poetry
#            refuserait un patch inférieur.
#   mineure  même majeure.mineure, quel que soit le patch. RIEN n'épingle le
#            patch du venv d'OUTILLAGE : l'exiger écarte le Python des
#            distributions dès qu'il est d'un patch en retard — 3.15.0
#            livré quand conf/ demande 3.15.2 — et force pyenv à COMPILER
#            CPython pour une différence qui ne gêne personne.
#
# L'égalité stricte, elle, rejetterait aussi un patch plus RÉCENT : c'est
# el_python_is_version, et elle ne sert qu'aux fournisseurs qui posent une
# version nommée.
el_python_is_compatible() {
  local exe="$1" want="$2" exigence="${3:-patch}" got
  [ -x "${exe}" ] || return 1
  got="$("${exe}" -c 'import platform;print(platform.python_version())' \
    2> /dev/null)"
  [ -n "${got}" ] || return 1
  # Même majeure.mineure : 3.13 ne convient pas à un pyproject borné à <3.13.
  [ "${got%.*}" = "${want%.*}" ] || return 1
  [ "${exigence}" = "mineure" ] && return 0
  # Patch au moins égal, comparé en version et non en chaîne (3.12.9 < 3.12.10).
  [ "$(printf '%s\n%s\n' "${want}" "${got}" | sort -V | head -1)" = "${want}" ]
}

# Interpréteur de la DISTRIBUTION qui conviendrait, s'il y en a un.
#
# Cherché avant toute compilation : sur une architecture émulée, bâtir CPython
# prend des dizaines de minutes quand il aboutit. Le nom suit la convention de
# toutes les distributions, « python3.12 ».
el_distro_python_exec() {
  local want="$1" exigence="${2:-patch}" exe
  # Des chemins SYSTEME, jamais « command -v » : dans un venv activé celui-ci
  # rend le python DU VENV, et l'on bâtirait un venv depuis un venv. Le PATH
  # d'une session interactive n'a rien à faire dans cette décision.
  # Le profil du systeme AVANT /usr/bin, et c'est NixOS qui l'impose : la-bas
  # /usr/bin est servi par envfs, qui repond a open() et a execve() mais PAS a
  # stat(). Le test « -x » y reussit donc, l'interpreteur s'execute, et
  # « python -m venv » echoue quand meme -- il stat son propre interpreteur
  # pour le recopier : « Error: [Errno 2] No such file or directory ». Le
  # chemin du profil, lui, est un vrai lien symbolique. Ailleurs il n'existe
  # pas, et la boucle passe a la suite sans rien couter.
  for exe in "/run/current-system/sw/bin/python${want%.*}" \
    "/usr/bin/python${want%.*}" "/usr/local/bin/python${want%.*}"; do
    if el_python_is_compatible "${exe}" "${want}" "${exigence}"; then
      echo "${exe}"
      return 0
    fi
  done
  return 1
}

# Installe la version via mise. Renvoie le chemin, ou échoue.
#
# Une version sans CPython précompilé échoue sans appeler mise. En mode
# « auto », el_warn_pyenv_fallback annonce ensuite pyenv ; avec
# EL_PYTHON_PROVIDER=mise, rien ne suit, d'où la raison dite ici.
el_mise_install() {
  local version="$1" exe mise
  if ! el_mise_a_precompile "${version}"; then
    if [ "${EL_PYTHON_PROVIDER:-auto}" = "mise" ]; then
      echo "mise ne publie aucun CPython precompile pour ${version} :" \
        "seul pyenv le fournit, et EL_PYTHON_PROVIDER=mise l'exclut." >&2
    fi
    return 1
  fi
  mise="$(el_mise_cmd)" || return 1
  echo "---- Python ${version} via mise (precompile) ----" >&2
  if [ "${EL_NON_INTERACTIVE:-}" = "1" ]; then
    # Un mise.toml non approuvé fait demander « Trust them? ». Les dossiers
    # au-dessus du checkout ne sont pas lus, et l'entrée vide fait échouer
    # mise sur un fichier non approuvé du checkout au lieu de le demander.
    MISE_CEILING_PATHS="$(dirname "${PWD}")" \
      "${mise}" install "python@${version}" < /dev/null >&2 || return 1
  else
    "${mise}" install "python@${version}" >&2 || return 1
  fi
  exe="$(el_mise_exec_path "${version}")" || return 1
  el_python_is_version "${exe}" "${version}" || return 1
  echo "${exe}"
}

# Imprime, un par ligne, les en-têtes C qui manquent pour que CPython bâtisse
# les modules dont l'installation dépend. Muet si tout est là.
#
# configure ne s'arrête sur aucun d'eux : il désactive le module en silence,
# la compilation va au bout, et c'est « ensurepip », à la toute fin, qui casse
# sur « zlib not available ». Demandé au préprocesseur et non à un chemin
# figé : ffi.h vit sous /usr/include/<triplet> chez Debian, pas chez Fedora.
#
# Chaque ligne : « en-tête paquet-apt paquet-dnf ».
el_pyenv_missing_headers() {
  local cc header apt dnf
  cc="$(command -v cc || command -v gcc)" || return 0
  while read -r header apt dnf; do
    printf '#include <%s>\n' "${header}" \
      | "${cc}" -E -x c - > /dev/null 2>&1 \
      || echo "${header} ${apt} ${dnf}"
  done << 'EOF'
zlib.h zlib1g-dev zlib-devel
openssl/ssl.h libssl-dev openssl-devel
ffi.h libffi-dev libffi-devel
bzlib.h libbz2-dev bzip2-devel
lzma.h liblzma-dev xz-devel
sqlite3.h libsqlite3-dev sqlite-devel
readline/readline.h libreadline-dev readline-devel
EOF
}

# Installe la version via pyenv, en posant pyenv lui-même au besoin.
el_pyenv_install() {
  local version="$1" root exe installer
  root="$(el_pyenv_root)"
  exe="$(el_pyenv_exec_path "${version}")"
  if [[ ! -d "${root}" ]]; then
    echo "---- Installation de pyenv dans ${root} ----" >&2
    # Téléchargé dans un fichier, PUIS exécuté. Quand curl alimente bash par
    # un tube, le statut du tube est celui de bash, qui rend 0 sur une entrée
    # vide : sans pipefail — que rien ne pose dans cette chaîne —, un
    # « || return 1 » placé après le tube ne se déclencherait jamais. Un
    # téléchargement raté mènerait alors à « pyenv: command not found », puis
    # à un échec de compilation, deux messages qui accusent la mauvaise
    # étape. Lu seul, le statut de curl nomme la vraie cause.
    #
    # « -f » : sans lui, curl écrit le CORPS d'une erreur HTTP — page d'erreur
    # de miroir, portail captif, 504 d'un cache hors ligne —, que bash
    # exécuterait ensuite comme un script.
    installer="$(mktemp)" || return 1
    if ! curl -fsSL -o "${installer}" \
      https://raw.githubusercontent.com/pyenv/pyenv-installer/master/bin/pyenv-installer; then
      echo "Telechargement de l'installateur pyenv impossible" \
        "(reseau ou cache) : pyenv n'est pas pose." >&2
      rm -f "${installer}"
      return 1
    fi
    if ! bash "${installer}" >&2; then
      echo "L'installateur de pyenv a echoue (voir ci-dessus)." >&2
      rm -f "${installer}"
      return 1
    fi
    rm -f "${installer}"
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
    local missing
    missing="$(el_pyenv_missing_headers)"
    if [ -n "${missing}" ]; then
      echo "En-tetes manquants, CPython se compilerait sans eux :" >&2
      echo "${missing}" | awk '{print "  " $1}' >&2
      if command -v apt-get > /dev/null 2>&1; then
        echo "  sudo apt-get install -y build-essential libncurses-dev" \
          "tk-dev uuid-dev libgdbm-dev libzstd-dev" \
          "$(echo "${missing}" | awk '{printf "%s ", $2}')" >&2
      elif command -v dnf > /dev/null 2>&1; then
        echo "  sudo dnf install -y" \
          "$(echo "${missing}" | awk '{printf "%s ", $3}')" >&2
      fi
      echo "  puis relancez." >&2
      return 1
    fi
    echo "---- Python ${version} via pyenv (compilation) ----" >&2
    # La liste des versions connues vient du dépôt git de pyenv : sans ce
    # « pull », une version récente est « not a known version ».
    (cd "${root}" && git pull) >&2 || true
    # Le configure de CPython 2.7 teste le signe de wchar_t par un programme
    # qui appelle exit() sans <stdlib.h>. Depuis GCC 14, une déclaration
    # implicite est une erreur en C99 : le test échoue, Py_UNICODE devient un
    # wchar_t signé, et une extension C compilée ensuite qui convertit un
    # char en Py_UNICODE corrompt chaque octet UTF-8 non ASCII. -fpermissive
    # rend ces tests à leur réponse ; la recette de pyenv y ajoute -std=c99.
    local cflags="${PYTHON_CFLAGS:-}"
    if [[ "${version}" == 2.7* ]]; then
      cflags="${cflags:+${cflags} }-fpermissive"
    fi
    # Le contrôle d'erreur d'origine testait un $retVal jamais affecté ici :
    # un échec de compilation passait inaperçu jusqu'au test d'existence.
    if ! yes n | PYTHON_CFLAGS="${cflags}" pyenv install "${version}" >&2; then
      echo "pyenv install ${version} a echoue." >&2
      return 1
    fi
  fi
  el_python_is_version "${exe}" "${version}" || return 1
  echo "${exe}"
}

# Annonce la compilation pyenv AVANT de la subir, et le geste qui l'évite :
# poser mise, ou lire ce que mise reproche quand il est déjà là. Muet si pyenv
# porte déjà la version, puisque rien ne sera compilé. Sans CPython
# précompilé pour la version, aucun geste ne l'évite : seule la durée est dite.
el_warn_pyenv_fallback() {
  local version="$1"
  [ -d "$(el_pyenv_root)/versions/${version}" ] && return 0
  if ! el_mise_a_precompile "${version}"; then
    echo "pyenv va COMPILER CPython ${version} : aucun Python precompile" >&2
    echo "  n'existe pour cette version. Quelques minutes." >&2
  elif el_mise_cmd > /dev/null; then
    echo "mise n'a pas pu fournir Python ${version} : repli sur pyenv," >&2
    echo "  qui COMPILE CPython. Pour lire ce que mise reproche :" >&2
    echo "    $(el_mise_cmd) install python@${version}   (reseau requis)" >&2
  elif [ "$(uname -m)" = "s390x" ]; then
    # mise ne publie aucun binaire s390x : « make install_mise » n'y fait rien.
    echo "pyenv va COMPILER CPython ${version} : aucun Python precompile" >&2
    echo "  n'existe pour s390x. Quelques minutes." >&2
  else
    echo "mise est absent : pyenv va etre pose, puis COMPILER CPython" >&2
    echo "  ${version} -- quelques minutes, bien plus sous emulation, et il" >&2
    echo "  lui faut une douzaine de -dev (openssl, zlib, readline, sqlite," >&2
    echo "  bzip2, xz, tk). Pour l'eviter : Ctrl+C, puis" >&2
    echo "    make install_mise" >&2
    echo "  qui pose un CPython precompile en quelques secondes, et relancez." >&2
  fi
}

# API publique : imprime le chemin absolu d'un interpréteur de cette version,
# ou rien (et rend non nul) si aucun fournisseur n'y parvient.
el_python_exec() {
  local version="$1" exigence="${2:-patch}"
  local provider="${EL_PYTHON_PROVIDER:-auto}" exe

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
    && exe="$(el_distro_python_exec "${version}" "${exigence}")"; then
    echo "Python $("${exe}" -V 2>&1 | awk '{print $2}') de la distribution :" \
      "aucune compilation." >&2
    echo "${exe}"
    return 0
  fi

  # 3) Rien de posé : il faut provisionner. mise d'abord quand il est là,
  #    parce qu'il télécharge au lieu de compiler ; absent, il est proposé
  #    devant un terminal, avant que pyenv ne compile.
  if [ "${provider}" != "pyenv" ]; then
    if exe="$(el_mise_install "${version}")"; then
      echo "${exe}"
      return 0
    fi
    local propose
    el_mise_proposer "${version}"
    propose=$?
    # Réponse manquante en mode non interactif : rien d'autre ne démarre.
    [ "${propose}" -eq 3 ] && return 1
    if [ "${propose}" -eq 0 ] && exe="$(el_mise_install "${version}")"; then
      echo "${exe}"
      return 0
    fi
    [ "${provider}" = "mise" ] && return 1
    # Une réponse négative a déjà dit que pyenv compile ; ne pas répéter le
    # conseil d'interrompre pour poser mise.
    [ "${propose}" -ne 2 ] && el_warn_pyenv_fallback "${version}"
  fi
  el_pyenv_install "${version}"
}
