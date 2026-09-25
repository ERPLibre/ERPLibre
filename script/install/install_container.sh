#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Moteur de conteneurs : Docker ou Podman.
#
#   sudo bash script/install/install_container.sh docker
#   sudo bash script/install/install_container.sh docker --rootless --amont
#   sudo bash script/install/install_container.sh podman
#
# Docker pose un démon que root possède : s'en servir sans sudo demande soit
# le groupe « docker », soit un démon par compte. Podman n'a pas de démon et
# tourne sous le compte de l'appelant — il n'y a donc rien à arbitrer.
#
# Le groupe « docker » équivaut à root : sa socket accepte de monter
# n'importe quel chemin de l'hôte dans un conteneur privilégié. Le script le
# dit avant de l'accorder, et ne l'accorde jamais sans qu'on l'ait demandé.
set -euo pipefail

log() { echo "[CONTENEUR] $*"; }
die() { echo "[CONTENEUR] ERREUR: $*" >&2; exit 1; }

usage() {
    cat <<'USAGE'
Usage : sudo bash script/install/install_container.sh <moteur> [options]

Moteurs :
  docker    un démon, son client, et un groupe pour l'atteindre
  podman    sans démon, sans privilège, compatible avec la ligne Docker

Options (docker seulement) :
  --groupe     défaut : ajoute le compte au groupe « docker »
  --rootless   un démon par compte, sans privilège ni groupe
  --amont      prend les paquets de Docker Inc. plutôt que ceux de la
               distribution. Docker Inc. n'empaquette que pour debian,
               ubuntu, raspbian, fedora, centos, rhel, rocky et sles.
               Sur Arch, le mode sans privilège vient d'AUR et l'option
               est retirée d'elle-même ; ailleurs, elle est refusée

Sur Arch, « --rootless » pose docker-rootless-extras depuis AUR, par
l'assistant du compte visé (yay, paru, pikaur ou trizen). AUR n'est pas un
dépôt officiel : son contenu est bâti localement et n'est pas revu.
  --compte <n> le compte à habiliter, quand SUDO_USER ne le dit pas
USAGE
}

MOTEUR=""
MODE="groupe"
AMONT=false
COMPTE="${SUDO_USER:-}"

while [ $# -gt 0 ]; do
    case "$1" in
        docker|podman) MOTEUR="$1" ;;
        --groupe)      MODE="groupe" ;;
        --rootless)    MODE="rootless" ;;
        --amont)       AMONT=true ;;
        --compte)      shift; COMPTE="${1:-}" ;;
        -h|--help)     usage; exit 0 ;;
        *)             usage; die "option inconnue : $1" ;;
    esac
    shift
done

[ -n "$MOTEUR" ] || { usage; die "nommer le moteur : docker ou podman"; }

check_root() {
    [ "$(id -u)" -eq 0 ] || die "à lancer en root : sudo bash $0 ${MOTEUR}"
}

detect_os() {
    [ -f /etc/os-release ] || die "OS indéterminable (pas de /etc/os-release)"
    # shellcheck disable=SC1091
    . /etc/os-release
    OS="${ID}"
    OS_LIKE="${ID_LIKE:-}"
    log "OS détecté : ${OS}"
}

family() {
    case "$OS" in
        ubuntu|debian|linuxmint|pop|elementary|raspbian) echo debian; return ;;
        arch|manjaro|endeavouros|artix|garuda) echo arch; return ;;
        fedora|rhel|centos|almalinux|rocky) echo rhel; return ;;
        opensuse*|sles|sled) echo suse; return ;;
    esac
    case "$OS_LIKE" in
        *debian*|*ubuntu*) echo debian; return ;;
        *arch*)            echo arch;   return ;;
        *rhel*|*fedora*)   echo rhel;   return ;;
        *suse*)            echo suse;   return ;;
    esac
    die "famille de distribution inconnue : ${OS} (ID_LIKE=${OS_LIKE})"
}

# Un paquet existe-t-il dans les dépôts de cette machine ?
#
# Le nom de la composition change d'une version à l'autre d'une même
# distribution — « docker-compose-v2 » chez Debian 13, « docker-compose »
# avant. Demander au gestionnaire vaut mieux que de deviner d'après le nom
# de version, qui ne dit rien des dépôts réellement activés.
paquet_existe() {
    local fam="$1" p="$2"
    case "$fam" in
        debian) apt-cache show "$p" >/dev/null 2>&1 ;;
        arch)   pacman -Si "$p" >/dev/null 2>&1 ;;
        rhel)   { command -v dnf >/dev/null && dnf -q info "$p" >/dev/null 2>&1; } \
                    || yum -q info "$p" >/dev/null 2>&1 ;;
        suse)   zypper --non-interactive search -x "$p" >/dev/null 2>&1 ;;
    esac
}

# Le premier de la liste que les dépôts portent, ou rien.
premier_disponible() {
    local fam="$1"; shift
    local p
    for p in "$@"; do
        if paquet_existe "$fam" "$p"; then
            echo "$p"
            return 0
        fi
    done
    return 0
}

install_packages() {
    local fam="$1"; shift
    [ $# -gt 0 ] || return 0
    log "Installation : $*"
    case "$fam" in
        debian)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq
            # shellcheck disable=SC2086
            apt-get install -y --no-install-recommends $*
            ;;
        arch)
            # shellcheck disable=SC2086
            pacman -Sy --needed --noconfirm $*
            ;;
        rhel)
            # shellcheck disable=SC2086
            { command -v dnf >/dev/null && dnf install -y $*; } || yum install -y $*
            ;;
        suse)
            # shellcheck disable=SC2086
            zypper --non-interactive install $*
            ;;
    esac
}

# Les paquets du moteur, par famille. « premier_disponible » tranche là où le
# nom bouge ; une chaîne vide ne casse rien, install_packages l'ignore.
paquets_docker() {
    local fam="$1" compose
    compose=$(premier_disponible "$fam" docker-compose-v2 docker-compose)
    case "$fam" in
        debian) echo "docker.io ${compose}" ;;
        arch)   echo "docker docker-buildx ${compose}" ;;
        rhel)   echo "moby-engine ${compose}" ;;
        suse)   echo "docker ${compose}" ;;
    esac
}

# Podman sans privilège a besoin de trois choses au-delà du binaire : la
# délégation d'UID (newuidmap), une pile réseau en espace utilisateur, et un
# système de fichiers superposé sans privilège. Là où le noyau les porte déjà,
# le paquet est simplement absent des dépôts et « premier_disponible » le tait.
paquets_podman() {
    local fam="$1" reseau compose
    reseau=$(premier_disponible "$fam" passt slirp4netns)
    compose=$(premier_disponible "$fam" podman-compose)
    case "$fam" in
        debian) echo "podman uidmap fuse-overlayfs ${reseau} ${compose}" ;;
        arch)   echo "podman fuse-overlayfs ${reseau} ${compose}" ;;
        rhel)   echo "podman shadow-utils fuse-overlayfs ${reseau} ${compose}" ;;
        suse)   echo "podman shadow fuse-overlayfs ${reseau} ${compose}" ;;
    esac
}

# Les paquets que le mode rootless de Docker ajoute au socle.
paquets_docker_rootless() {
    local fam="$1"
    case "$fam" in
        debian) echo "uidmap dbus-user-session fuse-overlayfs slirp4netns" ;;
        arch)   echo "fuse-overlayfs slirp4netns" ;;
        rhel)   echo "shadow-utils fuse-overlayfs slirp4netns" ;;
        suse)   echo "shadow fuse-overlayfs slirp4netns" ;;
    esac
}

# Les distributions pour lesquelles Docker Inc. empaquette : la liste que
# porte le « case "$lsb_dist" » de son script d'installation. Ailleurs, ce
# script se télécharge, s'exécute et s'arrête sur « Unsupported
# distribution » — autant le dire avant, quand on peut encore proposer
# autre chose.
AMONT_SUPPORTE="ubuntu debian raspbian centos fedora rhel rocky sles"

amont_supporte() {
    local connue
    for connue in ${AMONT_SUPPORTE}; do
        [ "$OS" = "$connue" ] && return 0
    done
    return 1
}

# Le paquet AUR qui porte dockerd-rootless-setuptool.sh sur Arch. Les dépôts
# officiels ne le portent pas — « extra/docker » compte 207 fichiers et aucun
# ne mentionne rootless — et get.docker.com refuse arch. AUR est donc la seule
# voie vers le mode sans privilège de Docker sur cette famille.
AUR_ROOTLESS="docker-rootless-extras"

# L'assistant AUR de cette machine, ou rien.
#
# Aucun n'accepte d'être lancé en root : ils bâtissent avec makepkg, qui
# refuse root par construction. On cherche donc dans le PATH de CONNEXION du
# compte visé, et non dans celui de root — un assistant posé sous ~/.local/bin
# est invisible d'ici autrement.
aur_helper() {
    local compte="$1" candidat
    for candidat in yay paru pikaur trizen; do
        if sudo -u "$compte" sh -lc "command -v ${candidat}" >/dev/null 2>&1; then
            echo "$candidat"
            return 0
        fi
    done
    return 0
}

installer_aur() {
    local compte="$1" paquet="$2" helper
    [ -n "$compte" ] || die "aucun compte pour bâtir depuis AUR — passer --compte <nom>"
    helper=$(aur_helper "$compte")
    if [ -z "$helper" ]; then
        log "aucun assistant AUR (yay, paru, pikaur, trizen) pour ${compte}."
        conseil_rootless >&2
        die "impossible de poser ${paquet}"
    fi
    log "AUR : ${paquet} par ${helper}, bâti localement sous ${compte}."
    log "  AUR n'est pas un dépôt officiel : son contenu n'est pas revu."
    # L'assistant redemande sudo pour SA phase d'installation, sous le compte
    # visé : un mot de passe peut être demandé ici même si ce script tourne
    # déjà en root, les deux sessions sudo étant distinctes.
    sudo -u "$compte" "$helper" -S --needed --noconfirm "$paquet" \
        || die "${helper} n'a pas posé ${paquet}"
}

# Le dernier recours, quand aucune voie automatique ne reste. Podman est la
# réponse partout : sans privilège d'origine, sans démon, et les quatre
# familles l'ont dans leurs dépôts.
conseil_rootless() {
    if [ "$(family)" = "arch" ]; then
        cat <<CONSEIL
Le paquet « docker » d'Arch ne porte pas l'outil, et get.docker.com refuse
arch. Trois voies :
  · bâtir ${AUR_ROOTLESS} à la main :
      git clone https://aur.archlinux.org/${AUR_ROOTLESS}.git
      cd ${AUR_ROOTLESS} && makepkg -si
  · podman, dans extra, sans privilège d'origine :
      sudo bash script/install/install_container.sh podman
CONSEIL
        return
    fi
    if amont_supporte; then
        cat <<'CONSEIL'
Deux voies :
  · relancer avec --amont, qui prend les paquets de Docker Inc.
  · podman, sans privilège d'origine :
      sudo bash script/install/install_container.sh podman
CONSEIL
        return
    fi
    cat <<'CONSEIL'
Docker Inc. n'empaquette pas pour cette distribution. Podman est sans
privilège d'origine et se pose depuis ses dépôts :
      sudo bash script/install/install_container.sh podman
CONSEIL
}

# Les plages d'UID et de GID subordonnés, sans lesquelles aucun moteur sans
# privilège ne démarre : newuidmap les lit pour donner au conteneur des
# identités qui ne sont pas celles de l'hôte. Debian et Fedora les posent à la
# création du compte ; Arch et openSUSE laissent les fichiers vides, et l'outil
# s'arrête alors sur « could not find records for user in /etc/subuid » — une
# phrase qui n'accuse ni le moteur ni l'installation.
#
# La plage fait 65 536 identités, la taille qu'allouent useradd et usermod, et
# commence au premier multiple libre à partir de 100 000 : recouvrir la plage
# d'un autre compte donnerait à deux comptes les mêmes identités dans leurs
# conteneurs.
prochaine_plage() {
    local fichier="$1" debut=100000
    while grep -q ":${debut}:" "$fichier" 2>/dev/null; do
        debut=$((debut + 65536))
    done
    echo "$debut"
}

assurer_subid() {
    local compte="$1" debut
    [ -n "$compte" ] || return 0
    command -v usermod >/dev/null || return 0
    if ! grep -q "^${compte}:" /etc/subuid 2>/dev/null; then
        debut=$(prochaine_plage /etc/subuid)
        log "plage d'UID subordonnés pour ${compte} : ${debut}+65536"
        usermod --add-subuids "${debut}-$((debut + 65535))" "$compte" \
            || die "impossible de poser la plage d'UID pour ${compte}"
    fi
    if ! grep -q "^${compte}:" /etc/subgid 2>/dev/null; then
        debut=$(prochaine_plage /etc/subgid)
        log "plage de GID subordonnés pour ${compte} : ${debut}+65536"
        usermod --add-subgids "${debut}-$((debut + 65535))" "$compte" \
            || die "impossible de poser la plage de GID pour ${compte}"
    fi
}

installer_amont() {
    # Le script de Docker Inc. pose le dépôt de l'éditeur puis docker-ce et
    # docker-ce-rootless-extras. C'est la seule source de
    # dockerd-rootless-setuptool.sh : aucun dépôt Debian ni Arch ne le porte.
    log "Source : https://get.docker.com (dépôt de Docker Inc.)"
    command -v curl >/dev/null || die "curl absent — l'installer d'abord"
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh \
        || die "téléchargement de get-docker.sh impossible"
    sh /tmp/get-docker.sh
    rm -f /tmp/get-docker.sh
}

activer_service() {
    local unite="$1"
    command -v systemctl >/dev/null || { log "pas de systemd : rien à activer"; return 0; }
    systemctl enable --now "$unite" >/dev/null 2>&1 \
        || log "⚠ ${unite} ne démarre pas — « systemctl status ${unite} »"
}

ajouter_au_groupe() {
    local compte="$1"
    [ -n "$compte" ] || die "aucun compte à habiliter — passer --compte <nom>"
    getent group docker >/dev/null || groupadd docker
    usermod -aG docker "$compte"
    log "⚠ ${compte} est maintenant dans le groupe « docker », qui équivaut"
    log "  à root : sa socket monte n'importe quel chemin de l'hôte."
    log "  Le groupe ne prend effet qu'à la PROCHAINE ouverture de session."
    log "  Tout de suite, dans ce terminal : newgrp docker"
}

# Les unités « utilisateur » de systemd qui lancent dockerd sous le compte.
# Deux chemins y mènent, et c'est le RÉSULTAT qu'on cherche, jamais l'outil :
# dockerd-rootless-setuptool.sh les ÉCRIT, là où le paquet d'Arch les LIVRE
# déjà et ne fournit donc pas l'outil. Chercher l'outil concluait « rien ici
# ne le pose » sur une machine où tout était posé.
UNITE_ROOTLESS="/usr/lib/systemd/user/docker.socket"

rootless_pret() {
    command -v dockerd-rootless-setuptool.sh >/dev/null && return 0
    [ -f "${UNITE_ROOTLESS}" ] && return 0
    return 1
}

poser_rootless() {
    local compte="$1" uid
    [ -n "$compte" ] || die "aucun compte à habiliter — passer --compte <nom>"
    if ! rootless_pret; then
        log "ni l'outil d'installation ni les unités utilisateur ne sont là."
        conseil_rootless >&2
        die "mode sans privilège impossible en l'état"
    fi
    uid=$(id -u "$compte")
    # Le démon vit dans la session systemd du compte : sans linger, il meurt à
    # la déconnexion et le conteneur avec lui. À poser AVANT le reste, car
    # c'est lui qui fait naître /run/user/<uid> sur un compte non connecté.
    command -v loginctl >/dev/null && loginctl enable-linger "$compte" || true

    if command -v dockerd-rootless-setuptool.sh >/dev/null; then
        sudo -u "$compte" \
            XDG_RUNTIME_DIR="/run/user/${uid}" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" \
            dockerd-rootless-setuptool.sh install \
            || die "l'installation rootless a échoué pour ${compte}"
    else
        log "unités livrées par le paquet : activation de la socket du compte."
        sudo -u "$compte" \
            XDG_RUNTIME_DIR="/run/user/${uid}" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" \
            systemctl --user enable --now docker.socket \
            || die "docker.socket ne démarre pas pour ${compte}"
    fi

    # La socket est le seul témoin qui vaille : les unités peuvent être en
    # place et le démon refuser de naître, faute de plages subordonnées ou
    # d'espaces de noms utilisateur.
    if ! sudo -u "$compte" \
        XDG_RUNTIME_DIR="/run/user/${uid}" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" \
        systemctl --user is-active docker.socket >/dev/null 2>&1; then
        die "docker.socket reste inactive pour ${compte} — « systemctl --user status docker.socket »"
    fi
    log "docker.socket est active pour ${compte}."
    log "Ajouter à l'environnement du compte :"
    log "  export DOCKER_HOST=unix:///run/user/${uid}/docker.sock"
}

verifier() {
    local moteur="$1"
    command -v "$moteur" >/dev/null \
        || die "${moteur} toujours absent après installation"
    log "vérifié : $("$moteur" --version)"
}

check_root
detect_os
FAM=$(family)

# Le refus arrive avant le téléchargement : laisser get.docker.com s'exécuter
# pour s'arrêter lui-même sur « Unsupported distribution » aurait déjà posé
# son dépôt sur certaines familles.
# --amont demandé là où Docker Inc. n'empaquette pas. Sur Arch une autre voie
# existe (AUR), donc on retire le drapeau et on continue ; ailleurs il n'y a
# rien derrière, et s'arrêter vaut mieux que de télécharger un script qui
# refusera — après avoir posé son dépôt sur certaines familles.
if [ "$AMONT" = true ] && ! amont_supporte; then
    log "get.docker.com ne traite pas « ${OS} » : --amont est sans objet."
    if [ "$FAM" = "arch" ]; then
        log "  Le mode sans privilège passe par AUR ici. On continue."
        AMONT=false
    else
        conseil_rootless >&2
        die "--amont est sans objet sur cette distribution"
    fi
fi

# Le mode sans privilège exige dockerd-rootless-setuptool.sh, qui ne vient que
# de deux sources : les paquets de Docker Inc., ou AUR sur Arch. Le vérifier
# AVANT d'installer évite de poser un moteur entier pour s'arrêter juste après
# sur ce qui manquait dès le départ. Un outil déjà présent passe ce garde.
if [ "$MOTEUR" = "docker" ] && [ "$MODE" = "rootless" ] \
    && ! rootless_pret \
    && [ "$AMONT" != true ] && [ "$FAM" != "arch" ]; then
    log "ni l'outil d'installation ni les unités utilisateur ne sont là."
    conseil_rootless >&2
    die "mode sans privilège impossible en l'état"
fi

case "$MOTEUR" in
    docker)
        if [ "$AMONT" = true ]; then
            installer_amont
        else
            # shellcheck disable=SC2046
            install_packages "$FAM" $(paquets_docker "$FAM")
        fi
        if [ "$MODE" = "rootless" ]; then
            # shellcheck disable=SC2046
            install_packages "$FAM" $(paquets_docker_rootless "$FAM")
            if [ "$FAM" = "arch" ] && ! rootless_pret; then
                installer_aur "$COMPTE" "${AUR_ROOTLESS}"
            fi
            assurer_subid "$COMPTE"
            verifier docker
            poser_rootless "$COMPTE"
        else
            activer_service docker.service
            verifier docker
            ajouter_au_groupe "$COMPTE"
        fi
        ;;
    podman)
        # shellcheck disable=SC2046
        install_packages "$FAM" $(paquets_podman "$FAM")
        assurer_subid "$COMPTE"
        verifier podman
        # Podman ne demande ni service ni groupe : le binaire suffit. La
        # socket n'est utile qu'aux clients qui parlent l'API Docker.
        log "Podman tourne sans privilège. Pour les outils qui parlent"
        log "l'API Docker : systemctl --user enable --now podman.socket"
        ;;
esac

log "Terminé."
